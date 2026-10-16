import re
from collections.abc import Mapping

from fastapi import Request

DEFAULT_LANGUAGE = "zh-Hant"
SUPPORTED_LANGUAGES = ("zh-Hant", "zh-Hans", "yue-Hant-HK", "en")

# Public message keys are stable; protocol status/code fields are never translated.
MESSAGES: dict[str, dict[str, str]] = {
    "zh-Hans": {
        "service_alive": "服务运行正常",
        "service_ready": "API 与数据库已就绪",
        "education_not_configured": "升学 AI 服务尚未配置，请联系管理员。",
        "education_unavailable": "升学 AI 服务暂时不可用，请稍后重试。",
        "education_timeout": "分析等待超时，填写内容已保留，请稍后重试。",
        "education_invalid_response": "AI 返回结果格式异常，请重新分析。",
        "not_ready": "服务未就绪，请检查后端与数据库迁移。",
        "request_failed": "请求失败，请稍后重试。",
        "validation_error": "请求参数无效，请检查后重试。",
        "internal_error": "服务器内部错误，请稍后重试。",
        "http_400": "请求无效，请检查后重试。",
        "http_401": "请先登录后再操作。",
        "http_403": "你没有权限执行此操作。",
        "http_404": "请求的资源不存在。",
        "http_405": "不支持此请求方法。",
        "http_409": "数据发生冲突，请刷新后重试。",
        "http_422": "请求参数无效，请检查后重试。",
        "http_429": "请求过于频繁，请稍后重试。",
        "http_503": "服务暂时不可用，请稍后重试。",
        "field_missing": "缺少必填字段。",
        "field_type": "字段类型不正确。",
        "field_invalid": "字段值无效。",
    },
    "zh-Hant": {
        "service_alive": "服務運行正常",
        "service_ready": "API 與數據庫已就緒",
        "education_not_configured": "升學 AI 服務尚未設定，請聯絡管理員。",
        "education_unavailable": "升學 AI 服務暫時無法使用，請稍後重試。",
        "education_timeout": "分析等候逾時，填寫內容已保留，請稍後重試。",
        "education_invalid_response": "AI 回傳結果格式異常，請重新分析。",
        "not_ready": "服務未就緒，請檢查後端與數據庫遷移。",
        "request_failed": "請求失敗，請稍後重試。",
        "validation_error": "請求參數無效，請檢查後重試。",
        "internal_error": "伺服器內部錯誤，請稍後重試。",
        "http_400": "請求無效，請檢查後重試。",
        "http_401": "請先登入後再操作。",
        "http_403": "你沒有權限執行此操作。",
        "http_404": "請求的資源不存在。",
        "http_405": "不支援此請求方法。",
        "http_409": "數據發生衝突，請重新整理後重試。",
        "http_422": "請求參數無效，請檢查後重試。",
        "http_429": "請求過於頻繁，請稍後重試。",
        "http_503": "服務暫時無法使用，請稍後重試。",
        "field_missing": "缺少必填欄位。",
        "field_type": "欄位類型不正確。",
        "field_invalid": "欄位值無效。",
    },
    "yue-Hant-HK": {
        "service_alive": "服務運行正常",
        "service_ready": "API 同數據庫都準備好喇",
        "education_not_configured": "升學 AI 服務未設定，請聯絡管理員。",
        "education_unavailable": "升學 AI 服務暫時用唔到，請遲啲再試。",
        "education_timeout": "分析等候逾時，填寫內容已保留，請遲啲再試。",
        "education_invalid_response": "AI 回傳結果格式有問題，請重新分析。",
        "not_ready": "服務未準備好，請檢查後端同數據庫遷移。",
        "request_failed": "請求失敗，請遲啲再試。",
        "validation_error": "請求資料唔啱，請檢查清楚再試。",
        "internal_error": "伺服器出咗問題，請遲啲再試。",
        "http_400": "請求資料唔啱，請檢查清楚再試。",
        "http_401": "請先登入再繼續。",
        "http_403": "你冇權限做呢個操作。",
        "http_404": "搵唔到你要嘅資料。",
        "http_405": "唔支援呢個請求方式。",
        "http_409": "資料有衝突，請重新整理再試。",
        "http_422": "請求資料唔啱，請檢查清楚再試。",
        "http_429": "你嘅請求太密喇，請遲啲再試。",
        "http_503": "服務暫時用唔到，請遲啲再試。",
        "field_missing": "有必填資料未填。",
        "field_type": "資料類型唔啱。",
        "field_invalid": "填入嘅資料唔啱。",
    },
    "en": {
        "service_alive": "Service is running",
        "service_ready": "API and database are ready",
        "education_not_configured": "The education AI service is not configured. Contact the administrator.",
        "education_unavailable": "The education AI service is unavailable. Please try again later.",
        "education_timeout": "Analysis timed out. Your form is kept; please try again later.",
        "education_invalid_response": "The AI response format was invalid. Please analyse again.",
        "not_ready": "Service unavailable. Check the backend and database migrations.",
        "request_failed": "Request failed. Please try again later.",
        "validation_error": "Invalid request parameters. Please check and try again.",
        "internal_error": "Internal server error. Please try again later.",
        "http_400": "Invalid request. Please check and try again.",
        "http_401": "Please sign in to continue.",
        "http_403": "You do not have permission to perform this action.",
        "http_404": "The requested resource was not found.",
        "http_405": "This request method is not supported.",
        "http_409": "Data conflict. Please refresh and try again.",
        "http_422": "Invalid request parameters. Please check and try again.",
        "http_429": "Too many requests. Please try again later.",
        "http_503": "Service temporarily unavailable. Please try again later.",
        "field_missing": "This field is required.",
        "field_type": "Incorrect field type.",
        "field_invalid": "Invalid field value.",
    },
}


def supported_language(tag: str) -> str | None:
    parts = tag.strip().replace("_", "-").lower().split("-")
    if parts[0] == "yue" or parts[:2] == ["zh", "yue"]:
        return "yue-Hant-HK"
    if parts[0] == "en":
        return "en"
    if parts[0] == "zh":
        if "hans" in parts:
            return "zh-Hans"
        if "hant" in parts or any(region in parts for region in ("hk", "tw", "mo")):
            return "zh-Hant"
        return "zh-Hans"
    return None


def negotiate_language(header: str | None) -> str:
    """Resolve BCP 47 language ranges in descending Accept-Language quality order."""
    preferences: list[tuple[float, str]] = []
    excluded: set[str] = set()
    for item in (header or "").split(","):
        tag, *parameters = item.strip().split(";")
        quality = 1.0
        for parameter in parameters:
            name, _, value = parameter.strip().partition("=")
            if name.lower() == "q":
                quality = float(value) if re.fullmatch(r"(?:0(?:\.\d{0,3})?|1(?:\.0{0,3})?)", value) else -1.0
                break
        if quality < 0:
            continue
        language = "*" if tag == "*" else supported_language(tag)
        if language is None:
            continue
        if quality == 0:
            excluded.add(language)
        else:
            preferences.append((quality, language))
    # Python's stable sort preserves the client's order for equal quality values.
    for _, language in sorted(preferences, key=lambda item: item[0], reverse=True):
        if language == "*":
            for candidate in SUPPORTED_LANGUAGES:
                if candidate not in excluded:
                    return candidate
        elif language not in excluded:
            return language
    # No acceptable supported range: use the documented application default.
    return DEFAULT_LANGUAGE


def request_language(request: Request) -> str:
    language = getattr(request.state, "language", None)
    if language not in SUPPORTED_LANGUAGES:
        language = negotiate_language(request.headers.get("Accept-Language"))
    return language


def translate(request: Request, key: str, default: str | None = None) -> str:
    messages = MESSAGES[request_language(request)]
    return messages.get(key, default if default is not None else messages["request_failed"])


def validation_message(request: Request, error_type: str) -> str:
    if error_type == "missing":
        key = "field_missing"
    elif error_type.endswith(("_type", "_parsing")):
        key = "field_type"
    else:
        key = "field_invalid"
    return translate(request, key)


def localized_headers(request: Request, headers: Mapping[str, str] | None = None) -> dict[str, str]:
    result = dict(headers or {})
    vary = next((value for name, value in result.items() if name.lower() == "vary"), "")
    fields = [field.strip() for field in vary.split(",") if field.strip()]
    if "*" not in fields and "accept-language" not in {field.lower() for field in fields}:
        fields.append("Accept-Language")
    result = {name: value for name, value in result.items() if name.lower() not in {"vary", "content-language"}}
    return {**result, "Content-Language": request_language(request), "Vary": ", ".join(fields)}
