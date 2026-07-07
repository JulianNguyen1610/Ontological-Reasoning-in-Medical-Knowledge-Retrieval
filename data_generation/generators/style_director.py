"""
Luồng 2: Định hướng phong cách hành văn
Mô phỏng đặc trưng văn bản lâm sàng: viết tắt, lỗi chính tả, cú pháp tự do
"""
import random
from typing import Dict, List

class StyleDirector:
    def __init__(self):
        # Các từ viết tắt phổ biến trong y khoa Việt Nam
        self.abbreviations = {
            "tăng huyết áp": ["THA", "HA cao", "tăng HA"],
            "huyết áp": ["HA", "BP", "máu"],
            "nhịp tim": ["HR", "mạch", "NT"],
            "nhiệt độ": ["T°", "T", "thân nhiệt"],
            "nhịp thở": ["RR", "thở"],
            "đường huyết": ["ĐH", "glucose", "BS"],
            "creatinine": ["Cr", "creatinin"],
            "điện tâm đồ": ["ECG", "EKG", "ĐTĐ"],
            "x-quang": ["CXR", "XQ", "phim X-quang"],
            "bệnh nhân": ["BN", "bệnh nhân", "patient"],
            "nhập viện": ["NV", "admission"],
            "xuất viện": ["XV", "discharge"],
            "khoảng cách": ["q", "mỗi"],
            "trước khi ngủ": ["qhs", "tối", "bedtime"],
            "khi cần": ["prn", "khi cần", "PRN"],
            "đường uống": ["po", "uống", "đường miệng"],
            "viên nén": ["tab", "viên", "vien"],
            "miligram": ["mg", "mgm", "mgs"],
            "mililiter": ["ml", "mL", "cc"],
            "lần mỗi ngày": ["bid", "2 lần/ngày", "q12h"],
            "mỗi ngày": ["qd", "daily", "1 lần/ngày"],
            "tiền sử": ["TS", "P/H", "past history"],
            "triệu chứng": ["TC", "symptom", "triệu chứng"],
            "chẩn đoán": ["CD", "Dx", "diagnosis"],
            "kết quả xét nghiệm": ["KQXN", "lab result", "kết quả"],
        }
        
        # Lỗi chính tả phổ biến
        self.common_typos = {
            "amlodipine": ["amlodipin", "amlodipi", "amlodipine"],
            "metoprolol": ["metoprolon", "metoprolol", "metoprol"],
            "aspirin": ["aspirin", "asprin", "aspirin"],
            "paracetamol": ["paracetamol", "paracetamon", "panadol"],
            "creatinine": ["creatinin", "creatinine", "creatin"],
            "đau đầu": ["đầu đầu", "nhức đầu", "đau đâu"],
            "khó thở": ["khó thở", "kho thở", "khó thơ"],
            "viêm phổi": ["viêm phổi", "viêm phổi", "VP"],
            "tăng huyết áp": ["tăng HA", "THA", "tăng huyết áp"],
        }
        
        # Ký hiệu chuyên ngành
        self.medical_symbols = {
            "độ C": "°C",
            "miligram": "mg",
            "mililiter": "ml",
            "lần": "x",
            "không": "Ø",
            "dương tính": "(+)",
            "âm tính": "(-)",
            "bình thường": "BT",
            "theo y lệnh": "TYL",
        }
        
        # Phong cách ghi chú theo loại
        self.style_templates = {
            "discharge_summary": [
                "BN {age}t, {gender}, NV vì {complaint}.",
                "Tiền sử: {history}.",
                "Khám lâm sàng: {examination}.",
                "CD: {diagnosis}.",
                "Xét nghiệm: {labs}.",
                "Điều trị: {treatment}.",
                "XV dặn BN {instructions}.",
            ],
            "clinical_note": [
                "BN {age}t {gender}, than phiền {complaint} {duration}.",
                "TS: {history}",
                "Khám: {examination}",
                "KQXN: {labs}",
                "CD: {diagnosis}",
                "Điều trị: {treatment}",
            ],
            "admission_note": [
                "BN {age}t {gender} nhập viện lúc {time}.",
                "Lý do NV: {complaint}.",
                "Bệnh sử: {history}.",
                "Tiền sử bệnh: {past_history}.",
                "Khám lâm sàng: {examination}.",
                "Chẩn đoán sơ bộ: {diagnosis}.",
                "Kế hoạch điều trị: {treatment}.",
            ],
            "progress_note": [
                "Ngày {day}: BN {status}.",
                "TC: {symptoms}.",
                "Khám: {examination}.",
                "Xét nghiệm: {labs}.",
                "Điều trị: {treatment}.",
                "Đánh giá: {assessment}.",
            ],
            "medication_list": [
                "Danh sách thuốc:",
                "{medications}",
                "Dặn dò: {instructions}",
            ],
            "lab_report": [
                "KẾT QUẢ XÉT NGHIỆM",
                "BN: {patient_name}",
                "Ngày: {date}",
                "{lab_results}",
                "Kết luận: {conclusion}",
            ],
            "imaging_report": [
                "BÁO CÁO CHẨN ĐOÁN HÌNH ẢNH",
                "Loại: {imaging_type}",
                "Kỹ thuật: {technique}",
                "Mô tả: {description}",
                "Kết luận: {conclusion}",
            ],
        }
    
    def apply_style(self, text: str, style: str, noise_level: float = 0.3) -> str:
        """Áp dụng phong cách và nhiễu vào văn bản"""
        # 1. Áp dụng viết tắt
        if random.random() < noise_level:
            text = self._inject_abbreviations(text)
        
        # 2. Áp dụng lỗi chính tả
        if random.random() < noise_level * 0.5:
            text = self._inject_typos(text)
        
        # 3. Áp dụng ký hiệu chuyên ngành
        if random.random() < noise_level * 0.7:
            text = self._inject_symbols(text)
        
        # 4. Loại bỏ dấu câu thừa
        if random.random() < noise_level * 0.3:
            text = self._remove_redundant_punctuation(text)
        
        # 5. Rút gọn ngữ pháp
        if random.random() < noise_level * 0.4:
            text = self._shorten_grammar(text)
        
        return text
    
    def _inject_abbreviations(self, text: str) -> str:
        """Thay thế từ đầy đủ bằng viết tắt"""
        for full, abbrevs in self.abbreviations.items():
            if full in text.lower() and random.random() < 0.3:
                abbrev = random.choice(abbrevs)
                text = text.replace(full, abbrev)
        return text
    
    def _inject_typos(self, text: str) -> str:
        """Tiêm lỗi chính tả nhẹ"""
        for correct, typos in self.common_typos.items():
            if correct in text.lower() and random.random() < 0.2:
                typo = random.choice(typos)
                text = text.replace(correct, typo)
        return text
    
    def _inject_symbols(self, text: str) -> str:
        """Thay thế bằng ký hiệu y khoa"""
        for full, symbol in self.medical_symbols.items():
            if full in text.lower() and random.random() < 0.4:
                text = text.replace(full, symbol)
        return text
    
    def _remove_redundant_punctuation(self, text: str) -> str:
        """Loại bỏ dấu câu thừa"""
        # Loại bỏ dấu chấm cuối câu
        if random.random() < 0.3:
            text = text.replace(".", "")
        # Loại bỏ dấu phẩy
        if random.random() < 0.2:
            text = text.replace(",", " ")
        # Loại bỏ dấu chấm phẩy
        if random.random() < 0.5:
            text = text.replace(";", " ")
        return text
    
    def _shorten_grammar(self, text: str) -> str:
        """Rút gọn ngữ pháp, bỏ chủ ngữ"""
        shortenings = [
            ("Bệnh nhân", "BN"),
            ("được chẩn đoán", "CD"),
            ("có tiền sử", "TS"),
            ("kết quả xét nghiệm", "KQXN"),
            ("được điều trị bằng", "điều trị"),
            ("bệnh nhân than phiền", "BN than"),
            ("bệnh nhân nhập viện", "BN NV"),
            ("bệnh nhân xuất viện", "BN XV"),
        ]
        for full, short in shortenings:
            if random.random() < 0.5:
                text = text.replace(full, short)
        return text
    
    def get_style_template(self, style: str) -> List[str]:
        """Lấy template theo phong cách"""
        return self.style_templates.get(style, self.style_templates["clinical_note"])
    
    def generate_noise_instructions(self, noise_level: float = 0.3) -> str:
        """Tạo chỉ thị nhiễu cho prompt"""
        instructions = []
        if random.random() < noise_level:
            instructions.append("- Sử dụng từ viết tắt y khoa (THA, BN, NV, XV, KQXN, v.v.)")
        if random.random() < noise_level * 0.5:
            instructions.append("- Có thể có lỗi chính tả nhẹ (amlodipin thay vì amlodipine)")
        if random.random() < noise_level * 0.7:
            instructions.append("- Dùng ký hiệu chuyên ngành (°C, mg, ml, (+), (-), Ø)")
        if random.random() < noise_level * 0.3:
            instructions.append("- Bỏ dấu câu thừa, viết ngắn gọn")
        if random.random() < noise_level * 0.4:
            instructions.append("- Rút gọn ngữ pháp, bỏ chủ ngữ nếu có thể")
        
        if not instructions:
            instructions.append("- Viết văn bản tự nhiên, rõ ràng")
        
        return "\n".join(instructions)