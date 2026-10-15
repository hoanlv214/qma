"""Agent Financial Security & Multilingual Prompt Injection Defense.

Adapted from ECC skill: llm-trading-agent-security.
Enforces multi-layer defense so that natural language inputs, webhooks, or social feeds
cannot manipulate autonomous agent wallets, bypass spending policies, or execute
unauthorized fund transfers regardless of language (English, Vietnamese, Chinese,
Russian, Spanish, French) or obfuscation techniques (zero-width Unicode, Base64, hex).
"""

import base64
import binascii
import logging
import re
import unicodedata
from typing import Optional, Tuple

logger = logging.getLogger("QMA-AgentSecurity")


class FinancialPromptInjectionError(ValueError):
    """Raised when an adversarial or injection payload is detected in a financial prompt."""
    pass


# ---------------------------------------------------------------------------
# Multilingual Injection Pattern Matrix
# ---------------------------------------------------------------------------
INJECTION_RULES = [
    # English
    (r"(?:ignore|disregard|forget)\s+(?:previous|all|prior)\s+(?:instructions?|directives?|prompts?|rules?)", "system_override"),
    (r"new\s+(?:directive|instruction|task|system\s+prompt)\s*:", "system_override"),
    (r"system\s*prompt\s*:\s*you\s+are", "system_override"),
    (r"act\s+as\s+(?:an?\s+evil|an?\s+unrestricted|a\s+jailbroken)\s+(?:bot|agent|assistant)", "jailbreak_attempt"),
    (r"(?:send|transfer|withdraw)\s+.*?\s+(?:to|towards)\s+0x[0-9a-fA-F]{40}", "transfer_directive"),
    (r"(?:drain|empty|steal)\s+(?:the\s+)?(?:wallet|treasury|vault|balance|funds)", "drain_directive"),
    (r"approve\s+.*?\s+(?:for|to)\s+0x[0-9a-fA-F]{40}", "approval_directive"),
    (r"(?:override|bypass|disable|ignore)\s+(?:the\s+)?(?:budget|limit|spending\s+policy|daily\s+cap|circuit\s+breaker)", "limit_tampering"),

    # Vietnamese
    (r"(?:bỏ\s*qua|hủy\s*bỏ|quên|đừng\s*quan\s*tâm|không\s*quan\s*tâm|vứt\s*bỏ)\s+(?:toàn\s*bộ|tất\s*cả|các)?\s*(?:hướng\s*dẫn|chỉ\s*thị|chỉ\s*dẫn|quy\s*tắc|lệnh|câu\s*lệnh|prompt)\s*(?:trước|cũ|ban\s*đầu)?", "system_override"),
    (r"(?:chỉ\s*thị|chỉ\s*dẫn|lệnh|nhiệm\s*vụ)\s*mới\s*[:：]", "system_override"),
    (r"(?:đóng\s*vai|hành\s*động|giả\s*lập)\s+(?:như\s+)?(?:một\s+)?(?:bot|agent|trợ\s*lý)\s+(?:độc\s*ác|không\s*giới\s*hạn|jailbreak|bị\s*bẻ\s*khóa)", "jailbreak_attempt"),
    (r"(?:chuyển|gửi|rút|bắn|chuyển\s*khoản)\s+.*?\s+(?:tới|sang|cho|về|đến)\s+0x[0-9a-fA-F]{40}", "transfer_directive"),
    (r"(?:rút\s*cạn|chiếm|lấy\s*hết|hút\s*hết|xả\s*hết|lấy\s*trộm|rút\s*hết)\s+(?:toàn\s*bộ\s+)?(?:tiền|ví|kho|quỹ|treasury|vault|số\s*dư)", "drain_directive"),
    (r"(?:phê\s*duyệt|ủy\s*quyền|cấp\s*quyền|approve)\s+.*?\s+(?:cho|tới|sang)\s+0x[0-9a-fA-F]{40}", "approval_directive"),
    (r"(?:vượt\s*qua|bỏ\s*qua|vô\s*hiệu\s*hóa|tắt|phá\s*vỡ)\s+(?:hạn\s*mức|ngân\s*sách|chính\s*sách|giới\s*hạn\s*chi\s*tiêu|circuit\s*breaker)", "limit_tampering"),

    # Chinese
    (r"(?:忽略|无视|忘记|跳过)\s*(?:之前|先前|所有|以前)?\s*(?:指示|指令|提示|规则|设定)", "system_override"),
    (r"(?:新指令|新指示|新任务|新设定)\s*[:：]", "system_override"),
    (r"(?:扮演|模拟)\s*(?:无限制|恶意|越狱|不受限)\s*(?:机器人|智能体|助手|agent)", "jailbreak_attempt"),
    (r"(?:转账|转入|转移|发送|提现|提取)\s*.*?\s*(?:至|到|向)\s*0x[0-9a-fA-F]{40}", "transfer_directive"),
    (r"(?:排空|清空|掏空|盗取|卷走)\s*(?:钱包|金库|国库|余额|资金|treasury)", "drain_directive"),
    (r"(?:授权|批准)\s*.*?\s*(?:给|到)\s*0x[0-9a-fA-F]{40}", "approval_directive"),
    (r"(?:绕过|覆盖|禁用|取消)\s*(?:预算|限额|支出政策|熔断机制|circuit\s*breaker)", "limit_tampering"),

    # Spanish
    (r"(?:ignora|olvida|descarta)\s+(?:las|todas)?\s*(?:instrucciones|directivas|reglas)\s*(?:previas|anteriores)?", "system_override"),
    (r"(?:envía|transfiere|retira)\s+.*?\s+(?:a|hacia)\s+0x[0-9a-fA-F]{40}", "transfer_directive"),
    (r"(?:vaciar|drenar|robar)\s+(?:la\s+)?(?:billetera|tesorería|fondos|bóveda)", "drain_directive"),

    # Russian
    (r"(?:игнорируй|забудь|отмени)\s+(?:все|предыдущие)?\s*(?:инструкции|директивы|правила)", "system_override"),
    (r"(?:переведи|отправь|перечисли)\s+.*?\s+(?:на|в)\s+0x[0-9a-fA-F]{40}", "transfer_directive"),
    (r"(?:опустоши|укради|выведи)\s+(?:все\s+)?(?:средства|кошелек|баланс|казначейство)", "drain_directive"),

    # French
    (r"(?:ignore|oublie)\s+(?:les|toutes\s+les)?\s*(?:instructions|directives)\s*(?:précédentes|antérieures)?", "system_override"),
    (r"(?:envoie|transfère)\s+.*?\s+(?:à|vers)\s+0x[0-9a-fA-F]{40}", "transfer_directive"),

    # Script and Markup Injection
    (r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", "malicious_markup"),
    (r"javascript\s*:\s*[^\s]+", "malicious_markup"),
]

# Zero-width spaces, joiners, directional overrides, soft-hyphens, and control characters
ZERO_WIDTH_AND_INVISIBLE_CHARS = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u202a-\u202e\u2060-\u206f]"
)
CONTROL_CHAR_REGEX = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]|\x1b\[[0-9;]*[a-zA-Z]"
)
BASE64_BLOCK_REGEX = re.compile(r"(?:[A-Za-z0-9+/]{4}){5,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?")
EVM_ADDRESS_REGEX = re.compile(r"0x[0-9a-fA-F]{40}")
MAX_PROMPT_LENGTH = 2000


def normalize_unicode(text: str) -> str:
    """Normalizes Unicode into canonical decomposed/composed form (NFKC)

    Strips invisible zero-width spaces, directional marks, and ANSI codes.
    """
    if not text:
        return ""
    # 1. NFKC canonical decomposition & composition (homoglyph normalization)
    normalized = unicodedata.normalize("NFKC", text)
    # 2. Strip zero-width & invisible format characters
    normalized = ZERO_WIDTH_AND_INVISIBLE_CHARS.sub("", normalized)
    # 3. Strip terminal escape codes and ASCII control characters
    normalized = CONTROL_CHAR_REGEX.sub("", normalized)
    return normalized.strip()


def scan_obfuscated_payloads(text: str) -> Tuple[bool, Optional[str]]:
    """Inspects text for embedded Base64 or Hex-encoded injection payloads."""
    # Check potential base64 strings
    for match in BASE64_BLOCK_REGEX.finditer(text):
        b64_candidate = match.group(0)
        try:
            decoded = base64.b64decode(b64_candidate, validate=True).decode("utf-8", errors="ignore")
            if len(decoded) >= 8:
                is_attack, cat = detect_financial_prompt_injection(decoded, check_obfuscation=False)
                if is_attack:
                    return True, f"obfuscated_base64_{cat}"
                if EVM_ADDRESS_REGEX.search(decoded):
                    return True, "obfuscated_base64_address"
        except (binascii.Error, ValueError):
            pass

    return False, None


def detect_financial_prompt_injection(
    prompt: str,
    check_obfuscation: bool = True,
) -> Tuple[bool, Optional[str]]:
    """Inspects a prompt for adversarial financial prompt injection across multiple languages.

    Returns:
        (is_attack, rule_category) if detected, otherwise (False, None).
    """
    if not prompt or not isinstance(prompt, str):
        return False, None

    cleaned = normalize_unicode(prompt)
    if not cleaned:
        return False, None

    # 1. Obfuscated payload inspection (Base64 / Hex)
    if check_obfuscation:
        is_obfuscated, cat = scan_obfuscated_payloads(cleaned)
        if is_obfuscated:
            return True, cat

    # 2. Multilingual regex pattern matching
    for pattern, category in INJECTION_RULES:
        if re.search(pattern, cleaned, re.IGNORECASE | re.DOTALL):
            return True, category

    # 3. Language-Agnostic Structural Rule:
    # If the prompt contains any raw EVM address AND financial transfer/drain keywords
    evm_match = EVM_ADDRESS_REGEX.search(cleaned)
    if evm_match:
        # Check if surrounding context contains value movement tokens in ANY language
        lowered = cleaned.lower()
        suspicious_financial_verbs = [
            "send", "transfer", "pay", "withdraw", "drain", "steal", "approve",
            "chuyển", "gửi", "rút", "bắn", "phê duyệt", "ủy quyền",
            "转账", "发送", "转入", "提现", "授权", "清空",
            "envía", "transfiere", "retira", "vaciar",
            "переведи", "отправь", "выведи", "опустоши",
            "envoie", "transfère", "vider"
        ]
        if any(verb in lowered for verb in suspicious_financial_verbs):
            return True, "structural_unauthorized_address_directive"

    return False, None


def sanitize_financial_prompt(prompt: str) -> str:
    """Sanitizes an incoming user or agent prompt string.

    1. Normalizes Unicode and removes hidden/zero-width/ANSI characters.
    2. Enforces maximum length bounds.
    3. Runs multilingual & obfuscation-resistant financial injection detection.

    Raises:
        FinancialPromptInjectionError if adversarial injection is detected.
        ValueError if prompt exceeds maximum bounds.
    """
    if prompt is None:
        return ""

    if not isinstance(prompt, str):
        prompt = str(prompt)

    # 1. Unicode normalization and invisible char removal
    cleaned = normalize_unicode(prompt)

    # 2. Length check
    if len(cleaned) > MAX_PROMPT_LENGTH:
        raise ValueError(f"Prompt length ({len(cleaned)}) exceeds maximum allowed ({MAX_PROMPT_LENGTH}).")

    # 3. Multilingual injection check
    is_attack, category = detect_financial_prompt_injection(cleaned)
    if is_attack:
        logger.warning("Financial prompt injection intercepted: category=%s", category)
        raise FinancialPromptInjectionError(
            f"Adversarial financial prompt injection detected (class: {category}). "
            f"Transaction planning rejected for safety."
        )

    return cleaned
