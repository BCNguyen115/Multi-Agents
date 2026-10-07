"""User-facing text for the data agent (English / Vietnamese) and number formatting.

Output language follows the language of the user's question. Nothing user-visible is hard-coded elsewhere in
the pipeline; adding a language means adding one more entry to ``MESSAGES``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

LANG_EN = "en"
LANG_VI = "vi"

_VI_MARKS = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯ]|[àáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", re.IGNORECASE)
_VI_WORDS = re.compile(r"\b(hay|phan tich|bieu do|du lieu|ve|tao|cho toi|thong ke|doanh|theo|cua|nhung|cac|tom tat|xu huong)\b")


def detect_language(text: str, default: str = LANG_EN) -> str:
    """Vietnamese if the text has Vietnamese letters or common unaccented Vietnamese words, else ``default``."""
    if not text:
        return default
    if _VI_MARKS.search(text):
        return LANG_VI
    folded = unicodedata.normalize("NFD", text.lower())
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    return LANG_VI if _VI_WORDS.search(folded) else default


MESSAGES: dict[str, dict[str, str]] = {
    LANG_EN: {
        "other": "Other",
        "records": "Records",
        "dashboard": "Data dashboard",
        "table": "Data table",
        # grains
        "grain.day": "day", "grain.week": "week", "grain.month": "month", "grain.quarter": "quarter", "grain.year": "year",
        "grain.days": "days", "grain.weeks": "weeks", "grain.months": "months", "grain.quarters": "quarters", "grain.years": "years",
        # aggregation phrases
        "agg.sum": "Total {m}", "agg.avg": "Average {m}", "agg.median": "Median {m}", "agg.min": "Minimum {m}",
        "agg.max": "Maximum {m}", "agg.count": "Number of records", "agg.nunique": "Distinct {m}",
        # chart titles / subtitles
        "chart.trend": "{am} by {grain}",
        "chart.rank": "Top {n} {dim} by {am}",
        "chart.share": "Share of {m} by {dim}",
        "chart.share_count": "Share of records by {dim}",
        "chart.compare": "{am} by {dim}",
        "chart.hist": "Distribution of {m}",
        "chart.scatter": "{y} vs {x}",
        "chart.corr": "Correlation between numeric columns",
        "chart.crosstab": "{a} × {b}",
        "chart.treemap": "Composition of {m} by {dim}",
        "chart.waterfall": "What moved {m}: {p0} → {p1}",
        "sub.partial": "Incomplete period {periods} excluded",
        "sub.top_of": "Showing top {shown} of {total}",
        "sub.min_group": "Groups with fewer than {n} rows are hidden",
        "sub.count_basis": "Counting records because {m} is averaged, not added",
        "sub.rho": "Spearman ρ = {rho}, n = {n}",
        "sub.clipped": "Axis shows the middle 99% of values; {n} extreme values are not drawn",
        "sub.sample_points": "Random sample of {shown} of {total} points",
        "sub.change": "Change {delta} ({pct}) between the two periods",
        # KPIs
        "kpi.records": "Records",
        "kpi.records_sub": "{n} rows analysed",
        "kpi.total": "Total {m}",
        "kpi.avg": "Average {m}",
        "kpi.distinct": "Distinct {d}",
        "kpi.distinct_sub": "Different values in {d}",
        "kpi.range": "Time coverage",
        "kpi.vs_prev": "vs {period}",
        "kpi.median_sub": "Median {v}",
        # story
        "story.sec.happened": "What happened",
        "story.sec.where": "Where and who",
        "story.sec.why": "Why (evidence)",
        "story.sec.related": "What is related",
        "story.sec.watch": "Watch out",
        "story.sec.actions": "Suggested actions",
        "story.sec.questions": "Questions to ask next",
        "story.headline_default": "{rows} rows across {cols} columns were analysed; no strong pattern stands out.",
        "story.hypothesis": "The data shows patterns, not causes; treat the items below as things to investigate.",
        "f.trend.up": "{m} rose {pct} from {first_period} to {last_period} (typical level {first} → {last} over {n} {grains}); the peak was {peak} in {peak_period}.",
        "f.trend.down": "{m} fell {pct} from {first_period} to {last_period} (typical level {first} → {last} over {n} {grains}); the peak was {peak} in {peak_period}.",
        "f.trend.flat": "{m} shows no clear trend over {n} {grains} ({first_period} to {last_period}); it ranged from {trough} in {trough_period} to {peak} in {peak_period}.",
        "f.period_change": "{m} in {last_period} was {last}, {delta_pct} vs {prev_period} ({prev}).",
        "f.period_change.yoy": " Compared with {yoy_period}: {yoy_pct}.",
        "f.contribution": "{m} moved by {delta} ({delta_pct}) from {from_period} to {to_period}. Most of the movement came from {dim}: {items}.",
        "f.contribution.item": "{name} ({delta}, {share} of the gross movement)",
        "f.composition.sum": "{top1} accounts for {top1_share} of total {m} across {dim}; the top 3 hold {top3_share}, and {pareto_n} of {n_groups} values make up 80%.",
        "f.composition.count": "{top1} is the largest {dim} group with {top1_share} of records ({top1_value}); the top 3 hold {top3_share}.",
        "f.composition.sum_small": "{top1} accounts for {top1_share} of total {m} across {dim}.",
        "f.composition.count_small": "{top1} is the largest {dim} group with {top1_share} of records ({top1_value}).",
        "f.ranking": "{top1} leads {dim} on {am} ({top1_value}), {ratio} the group average and {gap} above {top2} ({top2_value}); the lowest is {bottom1} ({bottom1_value}).",
        "f.ranking.nogap": "{top1} leads {dim} on {am} ({top1_value}), {ratio} the group average; the lowest is {bottom1} ({bottom1_value}).",
        "f.group_difference": "{m} differs meaningfully across {dim}: {best} averages {best_mean}, {diff_pct} more than {worst} ({worst_mean}) (n = {n}, statistically significant).",
        "f.correlation": "{a} and {b} move together ({strength} {direction} relationship, Spearman ρ = {rho}, n = {n}); this shows association, not cause.",
        "f.distribution": "{m} is highly uneven: the top 10% of records hold {top10} of the total and {outliers} records ({outlier_share}) are statistical outliers.",
        "f.distribution.skew": "{m} is skewed (skew {skew}); {outliers} records ({outlier_share}) are statistical outliers.",
        "f.anomaly": "Unusual {grain}: {items}.",
        "f.anomaly.item": "{period} ({m} {value} vs {expected} expected, {deviation})",
        "dir.up": "rose", "dir.down": "fell",
        "corr.strong": "strong", "corr.moderate": "moderate", "corr.positive": "positive", "corr.negative": "negative",
        "times": "{x}×",
        # implications
        "imp.concentration": "Results depend heavily on {top1}; track it separately and assess the dependency risk.",
        "imp.decline_driver": "Start investigating the decline with {name}, the largest single mover.",
        "imp.growth_driver": "Find out what worked for {name} and whether it can be repeated elsewhere.",
        "imp.outliers": "Review the outlier records before relying on averages of {m}.",
        "imp.correlation": "Test the relationship between {a} and {b} with a controlled comparison before acting on it.",
        "imp.anomaly": "Check whether {period} reflects a real event (campaign, outage, one-off) or a data error.",
        "imp.group": "Study what {best} does differently from {worst} in {dim}.",
        # caveats
        "cav.sampled": "The analysis uses a random sample of {used} of {total} rows.",
        "cav.partial": "The incomplete period {periods} is excluded from totals and trends.",
        "cav.missing": "Many values are missing in {cols} ({pct} or more).",
        "cav.duplicates": "{count} rows ({share}) are exact duplicates.",
        "cav.ambiguous_dates": "The day/month order in {cols} is ambiguous; month-first was assumed.",
        "cav.correlation_not_causation": "Correlation is not causation.",
        "cav.multi_sheet": "The workbook has {count} sheets; only '{sheet}' was analysed.",
        "cav.bad_lines_skipped": "Some malformed lines were skipped while reading the file.",
        "cav.constant_columns": "Columns without variation were ignored: {cols}.",
        # follow-up questions
        "nq.driver": "Which {dim} explain the change in {m}?",
        "nq.segment": "How does {m} differ across {dim}?",
        "nq.relate": "Does {a} relate to {b}?",
        "nq.time": "How has {m} changed by {grain}?",
        "nq.top": "Which {dim} contribute the most to {m}?",
        # messages
        "err.empty": "The file has no data rows to analyse.",
        "err.unsupported": "This file type is not supported. Please upload CSV, Excel (.xlsx), Parquet or JSON.",
        "err.parse": "The file could not be read. Please check its format and try again.",
        "err.unsafe": "The file holds far more data than its size suggests once it is unpacked, so it was not opened.",
        "err.too_large": "The file '{name}' is too large (limit {mb} MB).",
        "qa.answer_intro": "Result for your question:",
        "qa.no_result": "I could not compute a reliable answer to that question from this dataset.",
        "qa.rows_shown": "Showing {shown} of {total} rows.",
        "summary.title": "Summary of {name}",
        "summary.shape": "{rows} rows × {cols} columns",
        "summary.columns": "Columns",
        "summary.col.name": "Column", "summary.col.type": "Type", "summary.col.missing": "Missing", "summary.col.details": "Details",
        "err.no_file": "Please upload a CSV, Excel, Parquet or JSON file, then ask your analysis question.",
        "err.no_chart": "The data has no column combination that supports a meaningful chart.",
        "role.ROLE_IDENTIFIER": "identifier", "role.ROLE_TEMPORAL": "date/time", "role.ROLE_MEASURE": "number", "role.ROLE_RATIO": "ratio",
        "role.ROLE_ORDINAL": "ordered number", "role.ROLE_BOOLEAN": "flag", "role.ROLE_LOW_CARDINALITY": "category",
        "role.ROLE_HIGH_CARDINALITY": "category (many)", "role.ROLE_TEXT": "text", "role.ROLE_CONSTANT": "constant",
        "detail.range": "{low} to {high}, mean {mean}", "detail.top": "most common: {value} ({share})", "detail.dates": "{low} → {high}",
        "detail.distinct": "{n} distinct values",
    },
    LANG_VI: {
        "other": "Khác",
        "records": "Bản ghi",
        "dashboard": "Bảng điều khiển dữ liệu",
        "table": "Bảng dữ liệu",
        "grain.day": "ngày", "grain.week": "tuần", "grain.month": "tháng", "grain.quarter": "quý", "grain.year": "năm",
        "grain.days": "ngày", "grain.weeks": "tuần", "grain.months": "tháng", "grain.quarters": "quý", "grain.years": "năm",
        "agg.sum": "Tổng {m}", "agg.avg": "{m} trung bình", "agg.median": "Trung vị {m}", "agg.min": "{m} nhỏ nhất",
        "agg.max": "{m} lớn nhất", "agg.count": "Số bản ghi", "agg.nunique": "Số {m} khác nhau",
        "chart.trend": "{am} theo {grain}",
        "chart.rank": "Top {n} {dim} theo {am}",
        "chart.share": "Tỷ trọng {m} theo {dim}",
        "chart.share_count": "Tỷ trọng bản ghi theo {dim}",
        "chart.compare": "{am} theo {dim}",
        "chart.hist": "Phân phối của {m}",
        "chart.scatter": "{y} theo {x}",
        "chart.corr": "Tương quan giữa các cột số",
        "chart.crosstab": "{a} × {b}",
        "chart.treemap": "Cơ cấu {m} theo {dim}",
        "chart.waterfall": "Điều gì làm {m} thay đổi: {p0} → {p1}",
        "sub.partial": "Đã loại kỳ chưa đầy đủ {periods}",
        "sub.top_of": "Hiển thị {shown} trên {total}",
        "sub.min_group": "Ẩn các nhóm dưới {n} dòng",
        "sub.count_basis": "Đếm số bản ghi vì {m} được lấy trung bình, không cộng dồn",
        "sub.rho": "Spearman ρ = {rho}, n = {n}",
        "sub.clipped": "Trục hiển thị 99% giá trị ở giữa; {n} giá trị cực đoan không được vẽ",
        "sub.sample_points": "Mẫu ngẫu nhiên {shown} trên {total} điểm",
        "sub.change": "Thay đổi {delta} ({pct}) giữa hai kỳ",
        "kpi.records": "Số bản ghi",
        "kpi.records_sub": "Đã phân tích {n} dòng",
        "kpi.total": "Tổng {m}",
        "kpi.avg": "{m} trung bình",
        "kpi.distinct": "Số {d} khác nhau",
        "kpi.distinct_sub": "Số giá trị khác nhau của {d}",
        "kpi.range": "Khoảng thời gian",
        "kpi.vs_prev": "so với {period}",
        "kpi.median_sub": "Trung vị {v}",
        "story.sec.happened": "Điều gì đã xảy ra",
        "story.sec.where": "Ở đâu và ai",
        "story.sec.why": "Vì sao (bằng chứng)",
        "story.sec.related": "Điều gì có liên quan",
        "story.sec.watch": "Cần lưu ý",
        "story.sec.actions": "Hành động gợi ý",
        "story.sec.questions": "Câu hỏi nên đặt tiếp",
        "story.headline_default": "Đã phân tích {rows} dòng và {cols} cột; chưa thấy quy luật nổi bật.",
        "story.hypothesis": "Dữ liệu cho thấy quy luật, không chứng minh nguyên nhân; các mục bên dưới là điều cần kiểm tra thêm.",
        "f.trend.up": "{m} tăng {pct} từ {first_period} đến {last_period} (mức điển hình {first} → {last} trong {n} {grains}); đỉnh là {peak} vào {peak_period}.",
        "f.trend.down": "{m} giảm {pct} từ {first_period} đến {last_period} (mức điển hình {first} → {last} trong {n} {grains}); đỉnh là {peak} vào {peak_period}.",
        "f.trend.flat": "{m} không có xu hướng rõ rệt trong {n} {grains} ({first_period} đến {last_period}); dao động từ {trough} ({trough_period}) đến {peak} ({peak_period}).",
        "f.period_change": "{m} kỳ {last_period} là {last}, {delta_pct} so với {prev_period} ({prev}).",
        "f.period_change.yoy": " So với {yoy_period}: {yoy_pct}.",
        "f.contribution": "{m} thay đổi {delta} ({delta_pct}) từ {from_period} đến {to_period}. Phần lớn biến động đến từ {dim}: {items}.",
        "f.contribution.item": "{name} ({delta}, chiếm {share} tổng biến động)",
        "f.composition.sum": "{top1} chiếm {top1_share} tổng {m} theo {dim}; 3 giá trị đầu chiếm {top3_share}, và {pareto_n}/{n_groups} giá trị tạo nên 80%.",
        "f.composition.count": "{top1} là nhóm {dim} lớn nhất với {top1_share} số bản ghi ({top1_value}); 3 nhóm đầu chiếm {top3_share}.",
        "f.composition.sum_small": "{top1} chiếm {top1_share} tổng {m} theo {dim}.",
        "f.composition.count_small": "{top1} là nhóm {dim} lớn nhất với {top1_share} số bản ghi ({top1_value}).",
        "f.ranking": "{top1} dẫn đầu {dim} về {am} ({top1_value}), gấp {ratio} mức trung bình nhóm và cao hơn {top2} ({top2_value}) {gap}; thấp nhất là {bottom1} ({bottom1_value}).",
        "f.ranking.nogap": "{top1} dẫn đầu {dim} về {am} ({top1_value}), gấp {ratio} mức trung bình nhóm; thấp nhất là {bottom1} ({bottom1_value}).",
        "f.group_difference": "{m} khác biệt rõ rệt giữa các {dim}: {best} trung bình {best_mean}, cao hơn {worst} ({worst_mean}) {diff_pct} (n = {n}, có ý nghĩa thống kê).",
        "f.correlation": "{a} và {b} biến động cùng nhau (quan hệ {direction} {strength}, Spearman ρ = {rho}, n = {n}); đây là mối liên hệ, không phải quan hệ nhân quả.",
        "f.distribution": "{m} phân bổ rất không đều: 10% bản ghi đầu chiếm {top10} tổng và {outliers} bản ghi ({outlier_share}) là ngoại lai thống kê.",
        "f.distribution.skew": "{m} lệch mạnh (độ lệch {skew}); {outliers} bản ghi ({outlier_share}) là ngoại lai thống kê.",
        "f.anomaly": "{grain} bất thường: {items}.",
        "f.anomaly.item": "{period} ({m} {value} so với kỳ vọng {expected}, {deviation})",
        "dir.up": "tăng", "dir.down": "giảm",
        "corr.strong": "mạnh", "corr.moderate": "vừa", "corr.positive": "thuận chiều", "corr.negative": "nghịch chiều",
        "times": "{x} lần",
        "imp.concentration": "Kết quả phụ thuộc nhiều vào {top1}; nên theo dõi riêng và đánh giá rủi ro phụ thuộc.",
        "imp.decline_driver": "Bắt đầu tìm nguyên nhân sụt giảm từ {name}, yếu tố biến động lớn nhất.",
        "imp.growth_driver": "Tìm hiểu điều gì hiệu quả ở {name} và liệu có thể nhân rộng.",
        "imp.outliers": "Rà soát các bản ghi ngoại lai trước khi dùng giá trị trung bình của {m}.",
        "imp.correlation": "Kiểm tra mối quan hệ giữa {a} và {b} bằng so sánh có đối chứng trước khi hành động.",
        "imp.anomaly": "Kiểm tra {period} có phản ánh sự kiện thật (chiến dịch, sự cố, đột biến một lần) hay lỗi dữ liệu.",
        "imp.group": "Tìm hiểu {best} làm khác {worst} ở điểm nào trong {dim}.",
        "cav.sampled": "Phân tích dùng mẫu ngẫu nhiên {used} trên {total} dòng.",
        "cav.partial": "Kỳ chưa đầy đủ {periods} đã được loại khỏi tổng và xu hướng.",
        "cav.missing": "Nhiều giá trị bị thiếu ở {cols} ({pct} trở lên).",
        "cav.duplicates": "{count} dòng ({share}) là bản sao trùng khớp hoàn toàn.",
        "cav.ambiguous_dates": "Thứ tự ngày/tháng ở {cols} không rõ ràng; đã giả định tháng đứng trước.",
        "cav.correlation_not_causation": "Tương quan không phải quan hệ nhân quả.",
        "cav.multi_sheet": "Tệp có {count} sheet; chỉ phân tích sheet '{sheet}'.",
        "cav.bad_lines_skipped": "Một số dòng sai định dạng đã bị bỏ qua khi đọc tệp.",
        "cav.constant_columns": "Đã bỏ qua các cột không biến thiên: {cols}.",
        "nq.driver": "{dim} nào giải thích thay đổi của {m}?",
        "nq.segment": "{m} khác nhau thế nào giữa các {dim}?",
        "nq.relate": "{a} có liên quan đến {b} không?",
        "nq.time": "{m} thay đổi theo {grain} như thế nào?",
        "nq.top": "{dim} nào đóng góp nhiều nhất vào {m}?",
        "err.empty": "Tệp không có dòng dữ liệu nào để phân tích.",
        "err.unsupported": "Không hỗ trợ định dạng tệp này. Vui lòng tải lên CSV, Excel (.xlsx), Parquet hoặc JSON.",
        "err.parse": "Không đọc được tệp. Vui lòng kiểm tra định dạng và thử lại.",
        "err.unsafe": "Tệp chứa nhiều dữ liệu hơn hẳn dung lượng của nó khi giải nén nên không được mở.",
        "err.too_large": "Tệp '{name}' quá lớn (giới hạn {mb} MB).",
        "qa.answer_intro": "Kết quả cho câu hỏi của bạn:",
        "qa.no_result": "Tôi không tính được câu trả lời đáng tin cậy cho câu hỏi này từ bộ dữ liệu.",
        "qa.rows_shown": "Hiển thị {shown} trên {total} dòng.",
        "summary.title": "Tóm tắt {name}",
        "summary.shape": "{rows} dòng × {cols} cột",
        "summary.columns": "Các cột",
        "summary.col.name": "Cột", "summary.col.type": "Loại", "summary.col.missing": "Thiếu", "summary.col.details": "Chi tiết",
        "err.no_file": "Để phân tích dữ liệu, vui lòng tải lên tệp CSV, Excel, Parquet hoặc JSON rồi nhập câu hỏi phân tích của bạn.",
        "err.no_chart": "Dữ liệu không có tổ hợp cột nào phù hợp để dựng biểu đồ có ý nghĩa.",
        "role.ROLE_IDENTIFIER": "mã định danh", "role.ROLE_TEMPORAL": "ngày/giờ", "role.ROLE_MEASURE": "số", "role.ROLE_RATIO": "tỷ lệ",
        "role.ROLE_ORDINAL": "số có thứ tự", "role.ROLE_BOOLEAN": "cờ", "role.ROLE_LOW_CARDINALITY": "phân loại",
        "role.ROLE_HIGH_CARDINALITY": "phân loại (nhiều)", "role.ROLE_TEXT": "văn bản", "role.ROLE_CONSTANT": "hằng số",
        "detail.range": "{low} đến {high}, trung bình {mean}", "detail.top": "phổ biến nhất: {value} ({share})", "detail.dates": "{low} → {high}",
        "detail.distinct": "{n} giá trị khác nhau",
    },
}


def tr(lang: str, key: str, **params: Any) -> str:
    """Translate ``key`` (falls back to English, then to the key itself) and fill ``{placeholders}``."""
    template = MESSAGES.get(lang, {}).get(key) or MESSAGES[LANG_EN].get(key) or key
    return template.format(**params) if params else template


def _trim(text: str) -> str:
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_number(value: Optional[float], lang: str = LANG_EN) -> str:
    """Compact, unambiguous number: ``1,234`` / ``12.35`` / ``1.20M``. Identical for every language so text can be re-parsed."""
    if value is None:
        return "—"
    abs_value = abs(value)
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs_value >= limit:
            return f"{_trim(f'{value / limit:.2f}')}{suffix}"
    if abs_value >= 1000:
        return f"{value:,.0f}"
    if abs_value >= 1:
        return _trim(f"{value:,.2f}")
    if abs_value == 0:
        return "0"
    return _trim(f"{value:.3f}") if abs_value >= 0.001 else f"{value:.2e}"


def format_pct(fraction: Optional[float], signed: bool = False) -> str:
    """A fraction (0.125) as ``12.5%``; ``signed`` adds ``+``/``-``."""
    if fraction is None:
        return "—"
    text = _trim(f"{abs(fraction) * 100:.1f}") + "%"
    if signed:
        return ("+" if fraction >= 0 else "-") + text
    return text


def grain_word(lang: str, grain: str, plural: bool = False) -> str:
    return tr(lang, f"grain.{grain}{'s' if plural else ''}")


def agg_phrase(lang: str, agg: str, measure_label: str) -> str:
    return tr(lang, f"agg.{agg}", m=measure_label)
