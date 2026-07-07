"""
Utility functions cho xử lý văn bản y khoa
"""
import re
import unicodedata
from typing import List, Tuple, Optional

def normalize_text(text: str) -> str:
    """Chuẩn hóa văn bản tiếng Việt"""
    # Chuẩn hóa Unicode
    text = unicodedata.normalize('NFC', text)
    # Trim whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def find_all_occurrences(text: str, pattern: str) -> List[Tuple[int, int]]:
    """Tìm tất cả vị trí xuất hiện của pattern trong text"""
    positions = []
    start = 0
    while True:
        idx = text.find(pattern, start)
        if idx == -1:
            break
        positions.append((idx, idx + len(pattern)))
        start = idx + 1
    return positions

def levenshtein_distance(s1: str, s2: str) -> int:
    """Tính khoảng cách Levenshtein giữa 2 chuỗi"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]

def normalized_levenshtein_similarity(s1: str, s2: str) -> float:
    """Tính độ tương đồng Levenshtein chuẩn hóa (0-1)"""
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    distance = levenshtein_distance(s1, s2)
    return 1.0 - (distance / max_len)

def fuzzy_find_in_text(text: str, query: str, threshold: float = 0.85) -> Optional[Tuple[int, int]]:
    """Tìm mờ vị trí query trong text"""
    query_len = len(query)
    best_ratio = 0
    best_pos = None
    
    for i in range(len(text) - query_len + 1):
        window = text[i:i + query_len]
        ratio = normalized_levenshtein_similarity(query, window)
        
        if ratio > best_ratio:
            best_ratio = ratio
            best_pos = (i, i + query_len)
    
    if best_ratio >= threshold and best_pos:
        return best_pos
    
    return None

def extract_context(text: str, position: Tuple[int, int], context_size: int = 50) -> str:
    """Trích xuất ngữ cảnh xung quanh vị trí thực thể"""
    start, end = position
    context_start = max(0, start - context_size)
    context_end = min(len(text), end + context_size)
    return text[context_start:context_end]

def is_valid_entity_type(entity_type: str) -> bool:
    """Kiểm tra loại thực thể hợp lệ"""
    return entity_type in ["TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM", "CHẨN_ĐOÁN", "THUỐC"]

def is_valid_assertion(assertion: str) -> bool:
    """Kiểm tra thuộc tính hợp lệ"""
    return assertion in ["isNegated", "isFamily", "isHistorical"]

def format_entity_for_json(entity: dict) -> dict:
    """Định dạng thực thể cho output JSON"""
    formatted = {
        "text": entity["text"],
        "type": entity["type"],
        "assertions": entity.get("assertions", []),
        "position": list(entity.get("position", [0, 0]))
    }
    
    # Chỉ thêm candidates cho CHẨN_ĐOÁN và THUỐC
    if entity["type"] in ["CHẨN_ĐOÁN", "THUỐC"]:
        formatted["candidates"] = entity.get("candidates", [])
    else:
        formatted["candidates"] = []
    
    return formatted