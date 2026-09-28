"""
CÓC ĐI LÀM — Conversational Bridging Service (§5, §11)
Biến các câu hỏi khô cứng thành lời thoại phỏng vấn tự nhiên, thân thiện và chân thực
như các buổi phỏng vấn OJT/Fresher tại FPT Software và các tập đoàn công nghệ hàng đầu:
1. Tiếp nhận & Phản hồi chủ động (Active Listening & Empathic Feedback)
2. Cầu nối chuyển tiếp giữa các giai đoạn (Stage Segue & Contextual Transition)
3. Dẫn nhập câu hỏi tự nhiên, mềm mại thay vì tra khảo cộc lốc
"""

import json
import logging
import random
import time
import asyncio
from typing import Any
from google import genai
from google.genai import types
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ConversationalService:
    """Service tạo lời dẫn thoại & phản hồi tự nhiên cho phỏng vấn viên AI."""

    _cooldown_until: float = 0.0

    def __init__(self):
        self.settings = get_settings()
        self.gemini_client = None
        if self.settings.google_gemini_api_key:
            try:
                self.gemini_client = genai.Client(api_key=self.settings.google_gemini_api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini Client in ConversationalService: {e}")

    def format_opening_question(
        self,
        company: str = "FPT Software",
        role: str = "Java Backend Intern",
        candidate_name: str = "",
        seed_question: str = "",
    ) -> str:
        """Tạo lời chào mở đầu thân thiện, ấm áp và chuyên nghiệp."""
        name_str = f" {candidate_name}" if candidate_name else ""
        
        # Nếu seed_question đã có sẵn, lồng vào lời chào tự nhiên
        if "lý do" in seed_question.lower() or "động lực" in seed_question.lower() or "giới thiệu" in seed_question.lower():
            return (
                f"Chào em{name_str}, rất vui được gặp em trong buổi phỏng vấn OJT hôm nay tại {company}. "
                f"Để mở đầu buổi trao đổi một cách thoải mái, em hãy giới thiệu đôi nét về bản thân và chia sẻ "
                f"lý do em chọn ứng tuyển vị trí {role} cũng như những kỳ vọng em muốn học hỏi trong kỳ thực tập này nhé."
            )

        if seed_question:
            return (
                f"Chào em{name_str}, chào mừng em đến với buổi phỏng vấn OJT tại {company}. "
                f"Để bắt đầu, anh muốn hỏi em một câu hỏi mở đầu: {seed_question}"
            )

        return (
            f"Chào em{name_str}, rất vui được gặp em trong buổi phỏng vấn OJT hôm nay tại {company}. "
            f"Để mở đầu buổi trao đổi một cách thoải mái, em hãy chia sẻ ngắn gọn về lý do chọn ứng tuyển "
            f"vị trí {role} tại {company} và những mục tiêu em muốn đạt được trong kỳ thực tập này nhé."
        )

    async def bridge_turn_dialog(
        self,
        last_question: str,
        candidate_answer: str,
        evaluation: dict | None,
        next_action: str,
        prev_stage: str,
        next_stage: str,
        raw_question: str,
        role: str = "Java Backend Intern",
        company: str = "FPT Software",
        candidate_name: str = "",
    ) -> str:
        """
        Tổng hợp lời thoại tự nhiên của Interviewer cho lượt tiếp theo:
        [Phản hồi câu trả lời trước] + [Lời chuyển ý / chuyển giai đoạn] + [Câu hỏi được dẫn nhập tự nhiên]
        """
        # 1. Thử sinh bằng Gemini Flash nếu online và phản hồi nhanh
        if self.gemini_client and time.time() > self._cooldown_until:
            ai_bridge = await self._generate_ai_bridge(
                last_question=last_question,
                candidate_answer=candidate_answer,
                evaluation=evaluation,
                next_action=next_action,
                prev_stage=prev_stage,
                next_stage=next_stage,
                raw_question=raw_question,
                role=role,
                company=company,
            )
            if ai_bridge and len(ai_bridge.strip()) > 20:
                return ai_bridge.strip()

        # 2. Deterministic Fallback: Tự động ghép nối theo chuẩn phỏng vấn đời thực chuyên nghiệp
        return self._synthesize_rule_based_bridge(
            last_question=last_question,
            candidate_answer=candidate_answer,
            evaluation=evaluation,
            next_action=next_action,
            prev_stage=prev_stage,
            next_stage=next_stage,
            raw_question=raw_question,
            role=role,
            company=company,
        )

    def _synthesize_rule_based_bridge(
        self,
        last_question: str,
        candidate_answer: str,
        evaluation: dict | None,
        next_action: str,
        prev_stage: str,
        next_stage: str,
        raw_question: str,
        role: str,
        company: str,
    ) -> str:
        """Bộ sinh lời dẫn chuẩn xác, tự nhiên theo mô hình phỏng vấn chuyên nghiệp."""
        score = float(evaluation.get("score", 7.0)) if evaluation else 7.0
        awarded = evaluation.get("points_awarded", []) if evaluation else []
        missed = evaluation.get("points_missed", []) if evaluation else []

        # 1. Phản hồi câu trả lời vừa rồi (Acknowledgment & Feedback)
        feedback_part = ""
        highlight = awarded[0] if awarded else ""
        # Làm sạch highlight nếu có tiền tố "Khai thác tốt"
        highlight = highlight.replace("Khai thác tốt ", "").replace("Nêu rõ ", "").strip()

        if score >= 8.0:
            if "hr" in prev_stage or "motivation" in prev_stage:
                feedback_part = f"Cảm ơn em đã chia sẻ. Tinh thần chủ động và định hướng nghiêm túc với vị trí {role} tại {company} là một điểm cộng rất lớn."
            elif highlight:
                feedback_part = f"Rất tốt! Phần giải thích của em về {highlight} thể hiện tư duy xử lý vấn đề khá thực tế và có chiều sâu."
            else:
                feedback_part = "Rất tốt! Em đã trình bày rõ ràng, mạch lạc và nắm đúng trọng tâm vấn đề."
        elif score >= 6.0:
            if "hr" in prev_stage or "motivation" in prev_stage:
                feedback_part = f"Được rồi, anh ghi nhận mong muốn học hỏi và gắn bó của em với {company}."
            elif highlight:
                feedback_part = f"Được rồi, anh đã nắm được ý chính của em, đặc biệt là cách em tiếp cận {highlight}."
            else:
                feedback_part = "Được rồi, anh đã nắm được ý chính trong câu trả lời của em. Hướng tiếp cận đó cơ bản là hợp lý."
        else:
            if missed:
                missed_point = missed[0].replace("Chưa làm rõ ", "").strip()
                feedback_part = f"Anh hiểu hướng suy nghĩ của em rồi. Với vấn đề này trong thực tế triển khai, chúng ta sẽ cần lưu ý thêm về {missed_point}."
            else:
                feedback_part = "Cảm ơn em. Vấn đề này trong thực tế triển khai có khá nhiều góc độ cần xem xét."

        # 2. Cầu nối chuyển giai đoạn hoặc đào sâu (Transition Bridge)
        bridge_part = ""
        is_stage_transition = (prev_stage != next_stage) and bool(prev_stage and next_stage)

        if is_stage_transition:
            if "hr" in prev_stage and ("project" in next_stage or "star" in next_stage):
                bridge_part = "Phần định hướng ban đầu như vậy là rất rõ ràng. Bây giờ, chúng ta hãy cùng chuyển sang phần quan trọng tiếp theo: thẩm định kinh nghiệm thực chiến thông qua các dự án em đã ghi trong CV nhé."
            elif ("project" in prev_stage or "star" in prev_stage) and ("technical" in next_stage or "core" in next_stage):
                bridge_part = f"Qua phần dự án vừa rồi, anh thấy em đã có trải nghiệm thực tế rất tích cực. Tiếp theo đây, anh muốn cùng em bước vào phần kiểm tra kiến thức chuyên môn cốt lõi về {role} nhé."
            elif ("technical" in prev_stage or "core" in prev_stage) and ("scenario" in next_stage or "applied" in next_stage or "case" in next_stage):
                bridge_part = "Nền tảng kỹ thuật của em khá vững vàng. Bây giờ, anh muốn thử thách em bằng một tình huống sự cố thực tế thường xảy ra trên hệ thống Production nhé."
            elif "wrap_up" in next_stage:
                bridge_part = "Rất cảm ơn sự nỗ lực và phần thể hiện của em qua các câu hỏi vừa rồi. Chúng ta đã hoàn thành tất cả các nội dung đánh giá chuyên môn hôm nay."
            else:
                bridge_part = "Để tiếp tục buổi trao đổi hôm nay, chúng ta cùng chuyển sang chủ đề tiếp theo nhé."
        else:
            # Cùng stage: Đào sâu, thử thách hoặc hỗ trợ
            if next_action == "dig_deeper" or next_action == "challenge":
                bridge_part = "Liên quan trực tiếp đến phần kiến thức em vừa chia sẻ, anh muốn đào sâu thêm một chút."
            elif next_action == "scaffold":
                bridge_part = "Để giúp em dễ hình dung hơn, chúng ta hãy cùng nhìn bài toán này từ một góc độ đơn giản hơn nhé."
            else:
                bridge_part = "Tiếp theo, anh muốn trao đổi thêm với em về một khía cạnh quan trọng khác."

        # 3. Dẫn dắt câu hỏi một cách tự nhiên (Conversational Question Framing)
        clean_raw_q = raw_question.strip()
        framed_question = self._frame_question_naturally(clean_raw_q, role)

        # Kết hợp các thành phần
        parts = [p for p in [feedback_part, bridge_part, framed_question] if p]
        return " ".join(parts)

    def _frame_question_naturally(self, question_text: str, role: str) -> str:
        """Chuyển đổi câu hỏi dạng tra khảo cộc lốc thành câu hỏi đàm thoại tự nhiên."""
        q = question_text.strip()
        if not q:
            return q

        # Nếu câu hỏi đã dài và tự nhiên (đầy đủ chủ vị), giữ nguyên
        if len(q) > 80 and ("em hãy" in q.lower() or "theo em" in q.lower() or "chia sẻ" in q.lower() or "giải thích" in q.lower()):
            return q

        role_context = "Java Backend" if "java" in role.lower() else role

        # Mẫu 1: "Vấn đề X... là gì?"
        if q.lower().startswith("vấn đề") and "là gì" in q.lower():
            return f"Về mặt hiệu năng và độ ổn định hệ thống, {q[0].lower() + q[1:] if len(q) > 1 else q} Em chia sẻ cho anh hiểu nguyên nhân và các giải pháp em thường áp dụng để khắc phục nhé."

        # Mẫu 2: "Sự khác biệt giữa X và Y?"
        if "sự khác biệt giữa" in q.lower() or "khác nhau giữa" in q.lower():
            return f"Trong thực tế thiết kế hệ thống, chúng ta thường phải cân nhắc giữa các lựa chọn. {q} Em hãy chia sẻ quan điểm và tiêu chí lựa chọn của mình nhé."

        # Mẫu 3: "X là gì?" hoặc "X là gì? Nêu Y"
        if q.endswith(" là gì?") or " là gì?" in q:
            term = q.split(" là gì?")[0].strip()
            rest = q.split(" là gì?")[1].strip() if " là gì?" in q else ""
            if rest:
                return f"Trong quá trình làm việc với {role_context}, một khái niệm rất quen thuộc là {term}. Em có thể giải thích cho anh bản chất của {term} và {rest.lstrip('?., ')} được không?"
            return f"Trong quá trình làm việc với {role_context}, một khái niệm rất quen thuộc là {term}. Em có thể giải thích cho anh bản chất của {term} và vai trò của nó trong dự án không?"

        # Mẫu 4: Câu hỏi bắt đầu trực tiếp bằng động từ mệnh lệnh ("Giải thích...", "Nêu...", "Trình bày...")
        for prefix in ["Giải thích ", "Nêu ", "Trình bày ", "Phân tích ", "Mô tả "]:
            if q.startswith(prefix):
                content = q[len(prefix):]
                return f"Em có thể {prefix.lower()}{content} cho anh nắm rõ được không?"

        # Mặc định thêm lời dẫn nhẹ nhàng
        if not q.lower().startswith("em") and not q.lower().startswith("theo em") and not q.lower().startswith("hãy"):
            return f"Liên quan đến nội dung này, {q[0].lower() + q[1:] if len(q) > 1 else q}"

        return q

    async def _generate_ai_bridge(
        self,
        last_question: str,
        candidate_answer: str,
        evaluation: dict | None,
        next_action: str,
        prev_stage: str,
        next_stage: str,
        raw_question: str,
        role: str,
        company: str,
    ) -> str | None:
        """Sinh lời dẫn thoại bằng Gemini Flash với timeout nghiêm ngặt."""
        prompt = f"""Bạn là một Phỏng vấn viên công nghệ (Senior Technical Interviewer) giàu kinh nghiệm, thân thiện và chuyên nghiệp tại {company}.
Nhiệm vụ của bạn là nhận câu trả lời của ứng viên cho câu hỏi trước đó và dẫn dắt sang câu hỏi tiếp theo một cách cực kỳ tự nhiên như một cuộc trò chuyện phỏng vấn đời thực.

Ngữ cảnh:
- Vị trí phỏng vấn: {role}
- Công ty: {company}
- Câu hỏi vừa hỏi: "{last_question}"
- Câu trả lời của ứng viên: "{candidate_answer}"
- Điểm đánh giá câu trả lời: {evaluation.get('score', 7.0) if evaluation else 7.0}/10.0
- Điểm nổi bật ứng viên nói được: {json.dumps(evaluation.get('points_awarded', []) if evaluation else [], ensure_ascii=False)}
- Giai đoạn trước: {prev_stage} ➔ Giai đoạn tiếp theo: {next_stage}
- Nội dung câu hỏi tiếp theo cần hỏi: "{raw_question}"

Yêu cầu xuất ra:
- Viết 1 đoạn văn duy nhất (2-3 câu, tối đa 80 từ bằng tiếng Việt) từ ngôi thứ nhất ("anh" hoặc "tôi") xưng hô với ứng viên ("em").
- Câu 1: Phản hồi, công nhận hoặc nhận xét ngắn gọn, ấm áp về câu trả lời vừa rồi của ứng viên (dựa trên điểm và luận điểm ứng viên đã nêu).
- Câu 2: Chuyển tiếp mượt mà sang chủ đề hoặc giai đoạn tiếp theo.
- Câu 3: Dẫn nhập vào câu hỏi tiếp theo một cách đàm thoại, tự nhiên (KHÔNG dùng giọng tra khảo cộc lốc).
- Chỉ trả về đoạn văn lời nói phỏng vấn viên, không kèm giải thích hay định dạng thừa."""

        loop = asyncio.get_event_loop()

        def _call_gemini():
            for model_name in ["gemini-2.5-flash", "gemini-2.0-flash"]:
                try:
                    resp = self.gemini_client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.6,
                        ),
                    )
                    if resp and resp.text:
                        return resp.text.strip().replace('"', '').replace('**', '')
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "quota" in err_str.lower():
                        self.__class__._cooldown_until = time.time() + 90.0
                        return None
            return None

        try:
            return await asyncio.wait_for(loop.run_in_executor(None, _call_gemini), timeout=1.8)
        except Exception:
            return None


_conversational_service: ConversationalService | None = None


def get_conversational_service() -> ConversationalService:
    global _conversational_service
    if _conversational_service is None:
        _conversational_service = ConversationalService()
    return _conversational_service
