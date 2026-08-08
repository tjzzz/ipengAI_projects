"""Document segmenter: split an ordered paragraph list into rewrite tasks.

按文档结构把段落分组，供改写时决定"每次送 API 的文本块大小"。

核心能力：
    1. 结构保护（should_protect）—— 标题/图表/目录/短段 不改写
    2. 标题栈归属 —— 把正文段挂到最近的激活标题下
    3. 三种 mode 粒度：
        - low   : 单段（兼容旧值 paragraph）
        - median: 按二级标题(Heading 2)分块
        - high  : 按一级标题(Heading 1)分块
        无对应级别标题时退化为"段落块"（按动态 M 段一组）
    4. 返回有序的重建任务列表，含每个块需要送 API 的文本与应保护的段落。
"""

import math
import re


# 默认：无标题退化时的块数目标
DEFAULT_MEDIAN_BLOCKS = 7   # median 退化目标块数（正文越多每块段越多）
DEFAULT_HIGH_BLOCKS = 3     # high 退化目标块数


def _looks_like_title(text, words):
    """启发式判断一个 Normal 段是否像标题（无样式时的兜底）。"""
    if words > 15:
        return False
    stripped = text.strip()
    # 以数字/编号开头：1. 1.1 (1) 第一章 等
    if re.match(r'^(?:[\d]+[\s.、)）]+|[（(]\s*[\d]+[）)]\s*|第[一二三四五六七八九十百千0-9]+[章节部分篇])', stripped):
        return True
    # 无结尾句号（标题通常无句号）
    if not stripped.endswith(('.', '!', '?', '。', '！', '？')):
        # 且较短，视为标题
        if words <= 8:
            return True
    return False


class _StructureGuard:
    """段落保护判定器。

    基于 extract_text 阶段已标记好的段落属性做判断：
        - 表格占位 {'table': N}
        - 标题/目录类（is_heading=True）
        - 参考文献条目（is_reference=True，在 extract_text 阶段已标记）
        - 无格式正文且过短（< min_words）
        - 启发式"伪标题"识别

    无需维护前后文状态（参考文献标记已在 extract_text 解析时完成）。
    """

    def __init__(self, min_words=10):
        self.min_words = min_words

    def should_protect(self, para):
        if not para:
            return True
        # 表格占位
        if "table" in para:
            return True
        text = (para.get("text") or "").strip()
        if not text:
            return True

        # 参考文献条目（extract_text 已标记）
        if para.get("is_reference"):
            return True

        # 标题/目录类样式
        if para.get("is_heading", False):
            return True

        words = para.get("word_count", len(text.split()))
        # 无格式正文且过短
        if words < self.min_words:
            return True
        # 启发式"伪标题"识别
        if _looks_like_title(text, words):
            return True
        return False


def should_protect(para, min_words=10):
    """无状态的段落保护判定（供外部单段调用 / 测试用）。"""
    guard = _StructureGuard(min_words=min_words)
    return guard.should_protect(para)


# ---------- 标题栈归属 ----------

class _Section:
    """一个文档章节（以标题为边界）。"""

    def __init__(self, title_para=None, level=0):
        self.title = title_para   # 标题段落 dict 或 None（文档开头无标题区）
        self.level = level        # 标题级别，0 表示根/无标题
        self.body = []            # 归属的正文段列表


def _parse_heading_level(para):
    """从样式名解析标题级别。Heading 1->1, Heading 2->2 ... 非标题返回 None。"""
    if not para.get("is_heading"):
        return None
    style = (para.get("style") or "").lower()
    m = re.search(r'heading\s*(\d+)', style)
    if m:
        return int(m.group(1))
    if "title" in style:
        return 0
    # toc 目录类，级别用 0（不作为内容分块边界）
    return None


def build_section_tree(paragraphs):
    """把有序段落列表按标题层级组织成章节树。

    Returns:
        list[_Section]: 有序的章节列表，每个章节含 title 与 body 段。
        文档开头的非标题段归入一个无标题的根章节。
    """
    sections = []
    current = _Section(level=0)

    for para in paragraphs:
        level = _parse_heading_level(para)
        if level is not None and para.get("is_heading"):
            # 新标题：把当前章节收尾，开启新章节
            if current.body or current.title is not None:
                sections.append(current)
            current = _Section(title_para=para, level=level)
        else:
            current.body.append(para)

    if current.body or current.title is not None:
        sections.append(current)
    return sections


# ---------- mode 分块 ----------

def _heading_level(mode):
    """返回 mode 对应的标题级别边界。"""
    if mode == "median":
        return 2
    if mode == "high":
        return 1
    return None  # low 或无法识别


def segment(paragraphs, mode="low", min_words=10,
            median_blocks=DEFAULT_MEDIAN_BLOCKS, high_blocks=DEFAULT_HIGH_BLOCKS):
    """按 mode 把有序段落切分为"改写任务"。

    mode 枚举：low=单段 / median=按二级标题 / high=按一级标题。
    兼容旧值 paragraph（等价于 low）。

    Returns:
        list[dict]: 每个元素：
            {
                "type": "protected" | "rewrite" | "table",
                "text": 送 API 的文本（protected 时为原样保留文本）,
                "paragraphs": 该块涉及的段落 dict 列表,
            }
        按文档原顺序排列。
    """
    mode = (mode or "low").lower()
    # 兼容旧值 paragraph（等价于 low）
    if mode == "paragraph":
        mode = "low"
    guard = _StructureGuard(min_words=min_words)

    # 1) 单段模式：每段独立判断，保护段原样、正文段单独送
    if mode == "low":
        return _segment_paragraph(paragraphs, guard)

    # 2) median/high：按标题分块
    level_boundary = _heading_level(mode)
    return _segment_by_heading(paragraphs, mode, level_boundary, guard,
                               median_blocks, high_blocks)


def _segment_paragraph(paragraphs, guard):
    tasks = []
    for para in paragraphs:
        if "table" in para:
            tasks.append({"type": "table", "paragraphs": [para]})
        elif guard.should_protect(para):
            tasks.append({"type": "protected", "text": para["text"],
                          "paragraphs": [para]})
        else:
            tasks.append({"type": "rewrite", "text": para["text"],
                          "paragraphs": [para]})
    return tasks


def _segment_by_heading(paragraphs, mode, level_boundary, guard,
                        median_blocks, high_blocks):
    # 先构建章节树，按标题级别聚合
    sections = build_section_tree(paragraphs)

    # 判断是否存在可用边界标题
    usable = [s for s in sections if s.title and s.level == level_boundary]
    if usable:
        return _merge_sections(sections, level_boundary, guard)

    # 无对应级别标题 → 退化：按段落块分组
    return _segment_fallback(paragraphs, mode, guard, median_blocks, high_blocks)


def _merge_sections(sections, level_boundary, guard):
    """按给定标题级别把章节合并为"一个边界标题下"的组。

    组 = 一个边界标题（H1 for high / H2 for median）及其下的全部内容。
    组内：
        - 低级别标题（如 high 组里的 H2）：原样保留，作为组内 protected 元素
        - 正文段：合并送 API（保护段/短段除外）
        - 表格：强制切分（表格是强边界，前后语义不连续）
    """
    tasks = []
    group = None   # 当前组：{'rewrite_buffer'}

    def flush_group():
        nonlocal group
        if group is None:
            return
        if group["rewrite_buffer"]:
            body_text = "\n\n".join(p["text"] for p in group["rewrite_buffer"])
            tasks.append({"type": "rewrite", "text": body_text,
                          "paragraphs": group["rewrite_buffer"]})
        group = None

    def start_group():
        return {"rewrite_buffer": []}

    for section in sections:
        if section.title is not None:
            lvl = _parse_heading_level(section.title) or 0
            # 标题先经过 guard，维护引用模式状态（标题本身始终保护）
            guard.should_protect(section.title)
            if lvl == level_boundary:
                # 边界标题：结束当前块，标题原样保留，新开组
                flush_group()
                tasks.append({"type": "protected", "text": section.title["text"],
                              "paragraphs": [section.title]})
                group = start_group()
            elif lvl < level_boundary:
                # 比边界更高级的标题：结束当前块，标题原样保留
                flush_group()
                tasks.append({"type": "protected", "text": section.title["text"],
                              "paragraphs": [section.title]})
            else:
                # 比边界更低级的标题（high 组内的 H2/H3）：
                # 结束当前正文块（保证标题在原位置），标题原样保留
                flush_group()
                tasks.append({"type": "protected", "text": section.title["text"],
                              "paragraphs": [section.title]})
                group = start_group()
        # 章节正文
        for para in section.body:
            if group is None:
                group = start_group()
            if "table" in para:
                # 表格是强边界：先输出当前块，再输出表格占位
                flush_group()
                tasks.append({"type": "table", "paragraphs": [para]})
                group = start_group()
            elif guard.should_protect(para):
                flush_group()
                tasks.append({"type": "protected", "text": para["text"],
                              "paragraphs": [para]})
                group = start_group()
            else:
                group["rewrite_buffer"].append(para)

    flush_group()
    return tasks


def _segment_fallback(paragraphs, mode, guard, median_blocks, high_blocks):
    """无标题时的退化：把所有正文段按动态 M 段一组切块。"""
    # 第一遍：按顺序推进 guard 状态，记录每段的保护标记
    protect_flags = []
    for para in paragraphs:
        if "table" in para:
            protect_flags.append(True)
        else:
            protect_flags.append(guard.should_protect(para))

    body_paras = [p for p, f in zip(paragraphs, protect_flags)
                  if "table" not in p and not f]
    n = len(body_paras)
    if n == 0:
        # 全被保护，直接逐段输出保护
        return [_make_protected_or_table(p) for p in paragraphs]

    # 动态 M：目标块数
    target_blocks = median_blocks if mode == "median" else high_blocks
    m = max(1, math.ceil(n / target_blocks))

    tasks = []
    bi = 0
    for i, para in enumerate(paragraphs):
        if "table" in para:
            tasks.append({"type": "table", "paragraphs": [para]})
        elif protect_flags[i]:
            tasks.append({"type": "protected", "text": para["text"],
                          "paragraphs": [para]})
        else:
            # 该正文段属于当前改写块
            if bi == 0 or len(tasks) == 0 or tasks[-1].get("type") != "rewrite" or \
               len(tasks[-1]["paragraphs"]) >= m:
                tasks.append({"type": "rewrite", "text": para["text"],
                              "paragraphs": [para]})
            else:
                tasks[-1]["text"] += "\n\n" + para["text"]
                tasks[-1]["paragraphs"].append(para)
            bi += 1

    return tasks


def _make_protected_or_table(para):
    if "table" in para:
        return {"type": "table", "paragraphs": [para]}
    return {"type": "protected", "text": para["text"], "paragraphs": [para]}
