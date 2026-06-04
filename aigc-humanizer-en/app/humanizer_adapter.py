#!/usr/bin/env python3
"""
Humanizer adapter — abstracts the text humanization engine.
Uses the Adapter pattern so the app can switch between rule-based and API-driven engines.
"""

import os
import time
import json
import logging
from abc import ABC, abstractmethod
from urllib import request as urllib_request
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


class HumanizerAdapter(ABC):
    """Interface for text humanization adapters."""

    @abstractmethod
    def humanize(self, text, mode='academic'):
        """
        Humanize the given text.
        Args:
            text: The text to humanize.
            mode: 'academic' or 'aggressive' — controls transformation intensity.
        Returns:
            Humanized text string.
        """
        pass


class RuleBasedHumanizer(HumanizerAdapter):
    """Rule-based humanizer wrapping the existing humanize.py module."""

    def humanize(self, text, mode='academic'):
        """Humanize text using deterministic rule-based transformations."""
        from app.humanize import humanize_text
        return humanize_text(text, academic_mode=(mode == 'academic'))


class ApiHumanizer(HumanizerAdapter):
    """
    API-based humanizer calling ai-text-humanizer.com.

    Calls https://ai-text-humanizer.com/api.php with email/password auth.
    Supports automatic chunking for texts > 2000 words, rate limiting, and retries.
    """

    API_URL = "https://ai-text-humanizer.com/api.php"
    MAX_WORDS_PER_REQUEST = 2000
    RATE_LIMIT_DELAY = 1.2
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    REQUEST_TIMEOUT = 120

    def __init__(self, email=None, password=None):
        """
        Initialize the API humanizer.

        Args:
            email: ai-text-humanizer.com account email (falls back to env var)
            password: ai-text-humanizer.com account password (falls back to env var)
        """
        self.email = email or os.environ.get("AI_TEXT_HUMANIZER_EMAIL", "")
        self.password = password or os.environ.get("AI_TEXT_HUMANIZER_PASSWORD", "")

        if not self.email or not self.password:
            logger.warning(
                "AI_TEXT_HUMANIZER_EMAIL/ PASSWORD not configured. "
                "ApiHumanizer will raise an error if used."
            )

    def humanize(self, text, mode='academic'):
        """
        Humanize text via ai-text-humanizer.com API.

        Args:
            text: The text to humanize.
            mode: Ignored by this API (always uses its default behavior).

        Returns:
            Humanized text string.

        Raises:
            RuntimeError: If credentials are missing or API calls fail.
        """
        if not self.email or not self.password:
            raise RuntimeError(
                "ai-text-humanizer.com credentials not configured. "
                "Set AI_TEXT_HUMANIZER_EMAIL and AI_TEXT_HUMANIZER_PASSWORD in .env"
            )

        word_count = self._count_words(text)

        if word_count <= self.MAX_WORDS_PER_REQUEST:
            success, result = self._call_api(text)
            if not success:
                raise RuntimeError(f"API humanize failed: {result}")
            return result
        else:
            return self._process_large_text(text)

    def _call_api(self, text):
        """
        Single API call to ai-text-humanizer.com.

        Returns:
            (success: bool, result: str)
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                data = urlencode({
                    'email': self.email,
                    'pw': self.password,
                    'text': text
                }).encode('utf-8')

                req = urllib_request.Request(self.API_URL, data=data, method='POST')
                req.add_header('Content-Type', 'application/x-www-form-urlencoded;charset=utf-8')

                with urllib_request.urlopen(req, timeout=self.REQUEST_TIMEOUT) as resp:
                    result = resp.read().decode('utf-8', errors='replace').strip()

                if not result:
                    return False, "API returned empty response"

                # Check for common error indicators in short responses
                error_indicators = ['error', 'Error', 'ERROR', 'failed', 'Failed', 'invalid', 'Invalid']
                if len(result) < 500 and any(ind in result[:100] for ind in error_indicators):
                    return False, f"API error: {result}"

                return True, result

            except Exception as e:
                err_msg = str(e)
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"API call attempt {attempt + 1} failed: {err_msg}, retrying...")
                    time.sleep(self.RETRY_DELAY)
                else:
                    return False, f"API call failed after {self.MAX_RETRIES} attempts: {err_msg}"

        return False, "Max retries exceeded"

    def _process_large_text(self, text):
        """
        Split text into chunks and process each via API.

        Args:
            text: Full text to humanize.

        Returns:
            Humanized text string.

        Raises:
            RuntimeError: If any chunk fails.
        """
        chunks = self._split_text_smartly(text)
        total = len(chunks)
        logger.info(f"Text too large ({self._count_words(text)} words), splitting into {total} chunks")

        results = []
        for i, chunk in enumerate(chunks, 1):
            chunk_words = self._count_words(chunk)
            logger.info(f"Processing chunk {i}/{total} ({chunk_words} words)...")

            success, result = self._call_api(chunk)
            if not success:
                raise RuntimeError(f"Chunk {i}/{total} failed: {result}")

            results.append(result)

            if i < total:
                time.sleep(self.RATE_LIMIT_DELAY)

        return "\n\n".join(results)

    def _split_text_smartly(self, text):
        """
        Split text into chunks respecting the word limit.

        Args:
            text: Full text to split.

        Returns:
            List of text chunks, each within MAX_WORDS_PER_REQUEST.
        """
        chunks = []
        current_chunk = ""
        current_words = 0
        paragraphs = text.split('\n\n')

        for para in paragraphs:
            para_words = self._count_words(para)

            if para_words > self.MAX_WORDS_PER_REQUEST:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                    current_words = 0

                # Split by sentences for oversized paragraphs
                sentences = para.replace('. ', '. \n').replace('! ', '! \n').replace('? ', '? \n').split('\n')
                for sentence in sentences:
                    sentence_words = self._count_words(sentence)
                    if current_words + sentence_words <= self.MAX_WORDS_PER_REQUEST:
                        current_chunk += sentence + " "
                        current_words += sentence_words
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = sentence + " "
                        current_words = sentence_words
            else:
                if current_words + para_words <= self.MAX_WORDS_PER_REQUEST:
                    current_chunk += para + "\n\n"
                    current_words += para_words
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = para + "\n\n"
                    current_words = para_words

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    @staticmethod
    def _count_words(text):
        """Count words in text."""
        return len(text.split())