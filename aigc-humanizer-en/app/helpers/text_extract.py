"""Text extraction helpers: parse uploaded files into paragraph dicts.

支持 docx（保留 style / 编号 / 缩进 / 表格占位）、pdf、txt、md。
"""

import os
import logging


def _is_heading_style(style_name):
    """判断样式是否属于标题/目录类（这些段落不应参与改写）。

    覆盖常见 Word 内置样式：
    - Heading 1~9：各级标题
    - Title：文档标题
    - toc 1~9：目录条目
    """
    if not style_name:
        return False
    sn = style_name.lower().strip()
    if 'heading' in sn:
        return True
    if sn == 'title':
        return True
    if sn.startswith('toc'):
        return True
    return False


def _is_reference_heading(para):
    """判断段落是否为参考文献标题（Reference / Bibliography 等）。"""
    if not para or "text" not in para:
        return False
    text = para["text"].lower().strip()
    return 'reference' in text or 'bibliograph' in text


def mark_reference_sections(paragraphs):
    """修正段落列表：把"参考文献标题之后、下一个标题之前"的段落标记为 is_reference。

    参考文献识别依赖前后文（标题后到下一标题间的所有内容都属于文献），
    因此在 extract_text 解析出完整段落列表后做一次扫描修正。

    原列表会被就地修改（在原有 dict 上增加 is_reference 字段），并返回原列表。
    """
    in_reference = False
    for para in paragraphs:
        if "text" not in para:
            continue
        if para.get("is_heading", False):
            # 标题：更新参考文献模式（标题本身不标记为文献内容）
            in_reference = _is_reference_heading(para)
        else:
            if in_reference:
                para["is_reference"] = True
    return paragraphs


class _NumberingResolver:
    """解析 docx 的 numbering.xml，把段落自动编号还原为文本。

    负责建立  numId -> abstractNumId -> {ilvl: (numFmt, lvlText, left)}  映射，
    并维护各级编号计数器，生成实际的编号文本（如 '1.'、'(1)'、'a)'、'i.'、'•'）。

    用法：
        resolver = _NumberingResolver(doc)
        list_text, level, indent = resolver.resolve(p)   # p 为 Paragraph 对象
    无编号时返回 (None, None, None)。
    """

    _NUM_FMT_TO_STR = {
        'decimal': 'decimal',
        'lowerLetter': 'lowerLetter',
        'upperLetter': 'upperLetter',
        'lowerRoman': 'lowerRoman',
        'upperRoman': 'upperRoman',
        'bullet': 'bullet',
    }

    def __init__(self, doc):
        self._num_id_to_abs = {}      # numId -> abstractNumId
        self._abs_to_lvls = {}        # abstractNumId -> {ilvl: {'fmt','text','left'}}
        self._counters = {}           # (numId, ilvl) -> counter
        self._prev_key = None         # 前一段的 (numId, ilvl)，用于编号重置

        try:
            numbering = doc.part.numbering_part
        except Exception:
            numbering = None
        if numbering is None:
            return

        from docx.oxml.ns import qn as _qn
        element = numbering.element

        # 1) numId -> abstractNumId
        for num in element.findall(_qn('w:num')):
            num_id = num.get(_qn('w:numId'))
            abs_el = num.find(_qn('w:abstractNumId'))
            if num_id is not None and abs_el is not None:
                self._num_id_to_abs[num_id] = abs_el.get(_qn('w:val'))

        # 2) abstractNumId -> {ilvl: ...}
        for an in element.findall(_qn('w:abstractNum')):
            aid = an.get(_qn('w:abstractNumId'))
            lvls = {}
            for lv in an.findall(_qn('w:lvl')):
                ilvl = lv.get(_qn('w:ilvl'))
                if ilvl is None:
                    continue
                nf = lv.find(_qn('w:numFmt'))
                lt = lv.find(_qn('w:lvlText'))
                fmt = nf.get(_qn('w:val')) if nf is not None else None
                text = lt.get(_qn('w:val')) if lt is not None else None
                left = None
                pPr = lv.find(_qn('w:pPr'))
                if pPr is not None:
                    ind_el = pPr.find(_qn('w:ind'))
                    if ind_el is not None:
                        left = ind_el.get(_qn('w:left'))
                lvls[ilvl] = {'fmt': fmt, 'text': text, 'left': left}
            if aid is not None:
                self._abs_to_lvls[aid] = lvls

    def resolve(self, paragraph):
        """返回 (list_text, level, indent)；无编号返回 (None, None, None)。"""
        from docx.oxml.ns import qn as _qn
        pPr = paragraph._p.pPr
        if pPr is None:
            return None, None, None
        numPr = pPr.find(_qn('w:numPr'))
        if numPr is None:
            return None, None, None

        num_id = numPr.find(_qn('w:numId'))
        ilvl_el = numPr.find(_qn('w:ilvl'))
        if num_id is None:
            return None, None, None
        num_id = num_id.get(_qn('w:val'))
        ilvl = ilvl_el.get(_qn('w:val')) if ilvl_el is not None else '0'

        # 取缩进（优先段落自身 ind，其次编号定义里的 left）
        indent = None
        ind_el = pPr.find(_qn('w:ind'))
        if ind_el is not None:
            indent = ind_el.get(_qn('w:left'))

        # 查 abstractNum 定义
        abs_id = self._num_id_to_abs.get(num_id)
        lvl_def = None
        if abs_id:
            lvl_def = self._abs_to_lvls.get(abs_id, {}).get(ilvl)

        fmt = lvl_def['fmt'] if lvl_def else None
        lvl_text = lvl_def['text'] if lvl_def else None
        if indent is None and lvl_def:
            indent = lvl_def.get('left')

        key = (num_id, ilvl)
        # 编号重置：若与前一段不同列表或层级变浅，则重置对应计数
        if self._prev_key is not None and key != self._prev_key:
            prev_ilvl = int(self._prev_key[1]) if self._prev_key[1].isdigit() else 0
            cur_ilvl = int(ilvl) if ilvl.isdigit() else 0
            if cur_ilvl <= prev_ilvl:
                # 新列表或同级/更浅，重置当前及更浅层级
                self._counters.pop(key, None)
                for k in list(self._counters):
                    if int(k[1]) >= cur_ilvl:
                        self._counters.pop(k, None)
        self._prev_key = key

        counter = self._counters.get(key, 0) + 1
        self._counters[key] = counter

        # 生成编号文本
        rendered = self._render(fmt, counter, lvl_text)
        return rendered, int(ilvl), indent

    @staticmethod
    def _render(fmt, counter, lvl_text):
        """把 numFmt + lvlText 模板渲染成实际编号文本。"""
        # 计算 %1..%9 的替换值（这里列表仅一级，取 %1 或直接数值）
        if lvl_text is None:
            return str(counter)

        # 实际编号字符（按格式）
        num_str = _NumberingResolver._format_number(fmt, counter, lvl_text)

        # 模板中无 %N 占位符（如纯项目符号 '•'）时，直接返回编号字符
        if '%' not in (lvl_text or ''):
            return num_str

        # 用编号值替换模板中的 %1、%2...
        import re
        result = re.sub(r'%\d+', num_str, lvl_text, count=1)
        return result.strip()

    @staticmethod
    def _format_number(fmt, counter, lvl_text=None):
        if fmt == 'decimal':
            return str(counter)
        if fmt == 'lowerLetter':
            return _NumberingResolver._to_alpha(counter)
        if fmt == 'upperLetter':
            return _NumberingResolver._to_alpha(counter).upper()
        if fmt == 'lowerRoman':
            return _NumberingResolver._to_roman(counter)
        if fmt == 'upperRoman':
            return _NumberingResolver._to_roman(counter).upper()
        if fmt == 'bullet':
            # Wingdings 项目符号字符（\uf06c 等）转常见符号
            if lvl_text and '\uf06c' in lvl_text:
                return '\u2022'  # •
            if lvl_text and '\uf075' in lvl_text:
                return '\u25aa'  # ▪
            if lvl_text and '\uf06e' in lvl_text:
                return '\u25e6'  # ◦
            return '\u2022'
        return str(counter)

    @staticmethod
    def _to_alpha(n):
        """1->a, 2->b, ..., 26->z, 27->aa ..."""
        s = ''
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(ord('a') + r) + s
        return s

    @staticmethod
    def _to_roman(n):
        val = [
            (1000, 'm'), (900, 'cm'), (500, 'd'), (400, 'cd'),
            (100, 'c'), (90, 'xc'), (50, 'l'), (40, 'xl'),
            (10, 'x'), (9, 'ix'), (5, 'v'), (4, 'iv'), (1, 'i'),
        ]
        res = ''
        for v, r in val:
            while n >= v:
                res += r
                n -= v
        return res


def _build_paragraph(text, style=None, list_text=None, list_level=None, indent=None):
    """构建段落 dict：{'text':..., 'style':..., 'is_heading':..., 'word_count':...}。

    style 为 None 时（pdf/txt/md 无样式信息），不携带 style/is_heading 字段。
    可选附加字段：list_text（还原的编号/符号）、list_level（列表层级）、indent（缩进）。
    """
    text = text.strip()
    d = {
        "text": text,
        "word_count": len(text.split()),
    }
    if style is not None:
        d["style"] = style
        d["is_heading"] = _is_heading_style(style)
    if list_text is not None:
        d["list_text"] = list_text
        d["list_level"] = list_level
    if indent is not None:
        d["indent"] = indent
    return d


def extract_text_from_docx(filepath):
    """Extract paragraphs and tables from .docx file in document-flow order.

    段落：返回含 text / style / is_heading / word_count 的 dict。
    表格：不解析具体内容，返回占位 dict {'table': 1}（表格序号）。
    按文档原始顺序排列，保证 Q1 段 → 表格 → Q2 段的相对位置不变。

    Returns:
        list[dict]: 段落元素 或 表格占位元素
    """
    from docx import Document
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from docx.table import Table

    doc = Document(filepath)
    result = []
    table_idx = 0
    resolver = _NumberingResolver(doc)

    for child in doc.element.body.iterchildren():
        tag = child.tag.split('}')[-1]
        if tag == 'p':
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                continue
            style = p.style.name if p.style else None
            list_text, list_level, indent = resolver.resolve(p)
            result.append(_build_paragraph(
                text, style, list_text=list_text, list_level=list_level, indent=indent,
            ))
        elif tag == 'tbl':
            table_idx += 1
            result.append({"table": table_idx})

    return mark_reference_sections(result)


def extract_text_from_pdf(filepath):
    """Extract paragraphs from .pdf file.

    Detects Turnitin reports and skips the first 2 pages automatically.
    无段落样式信息，每段不带 style/is_heading。

    Returns:
        list[dict]: 每个元素含 text / word_count
    """
    import fitz
    doc = fitz.open(filepath)

    # Read first 2 pages to check for Turnitin
    first_two_pages_text = ""
    for i in range(min(2, len(doc))):
        first_two_pages_text += doc[i].get_text()

    is_turnitin = "turnitin" in first_two_pages_text.lower()

    page_count = len(doc)
    text_parts = []
    start_page = 2 if is_turnitin else 0
    for i in range(start_page, page_count):
        text_parts.append(doc[i].get_text())
    doc.close()

    if is_turnitin:
        logging.info(f"Turnitin report detected, skipped first 2 pages ({page_count} pages total)")

    # PDF 无段落结构，按空行粗分
    result = []
    for chunk in '\n\n'.join(text_parts).split('\n\n'):
        chunk = chunk.strip()
        if chunk:
            result.append(_build_paragraph(chunk))
    return result


def extract_text(filepath):
    """Extract paragraphs from an uploaded file.

    Returns:
        list[dict]: 段落列表。docx 携带 style/is_heading 字段；
                    pdf/txt/md 仅含 text/word_count（无样式信息）。
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.docx':
        # extract_text_from_docx 内部已做参考文献修正
        return extract_text_from_docx(filepath)
    elif ext == '.pdf':
        return mark_reference_sections(extract_text_from_pdf(filepath))
    elif ext in ('.txt', '.md'):
        result = []
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        for chunk in content.split('\n\n'):
            chunk = chunk.strip()
            if chunk:
                result.append(_build_paragraph(chunk))
        return mark_reference_sections(result)
    else:
        raise ValueError(f"Unsupported file format: {ext}")


def paragraph_list_to_text(paragraphs):
    """把段落 dict 列表拼回纯文本字符串（用 \\n\\n 分隔）。

    用于 AI 检测等需要字符串的场景。表格占位（{'table': N}，无 text 字段）
    会被自动忽略，不影响文本拼接。
    """
    return '\n\n'.join(p.get("text") for p in paragraphs if p.get("text"))
