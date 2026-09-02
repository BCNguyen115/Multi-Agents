# 💡 BỘ PROMPT MẪU DÀNH CHO MULTI-AGENT SYSTEM (Version v1.0.0)

> **Prompt Template Version:** `v1.0.0` | **Semantic Release Baseline**

Tài liệu này tổng hợp các câu hỏi mẫu và Prompt tối ưu được thiết kế riêng cho 3 Chế độ Agent trên hệ thống Enterprise Multi-Agent:
1. **🤖 RAG Agent** (Tra cứu & Trích xuất Tài liệu Nội bộ)
2. **📊 Data Agent** (Phân tích Dữ liệu CSV & Tạo Dashboard)
3. **🌐 Search Agent** (Tìm kiếm & Tổng hợp Thông tin Web Thời gian thực)

---

## 1. 🤖 RAG Agent (Tra cứu Tài liệu Nội bộ)
*Chuyên trách: Tra cứu câu trả lời chuẩn xác dựa trên các tài liệu hợp đồng NDA, MSA, phụ lục SOW, tài liệu kỹ thuật và quy trình doanh nghiệp đã được lưu trong cơ sở dữ liệu Vector (pgvector).*

### 📝 Nhóm 1: Tra cứu Thỏa thuận Bảo mật & Điều khoản Pháp lý (NDA / MSA)
* `"Điều khoản bảo mật thông tin trong hợp đồng NDA quy định như thế nào?"`
* `"Thời hạn hiệu lực của thỏa thuận bảo mật NDA là bao lâu và điều kiện gia hạn là gì?"`
* `"Bên nhận thông tin (Receiving Party) sẽ bị xử phạt như thế nào nếu làm rò rỉ thông tin bảo mật?"`
* `"Những trường hợp nào thông tin không được coi là Thông tin Bảo mật (Confidential Information)?"`
* `"Quy định về nghĩa vụ bảo mật sau khi chấm dứt hợp đồng kéo dài trong bao nhiêu năm?"`

### 📝 Nhóm 2: Tra cứu Phạm vi Công việc & Tiến độ Dự án (SOW / Project)
* `"Phạm vi công việc (Scope of Work - SOW) của dự án bao gồm những mốc bàn giao (Deliverables) chính nào?"`
* `"Nghĩa vụ và trách nhiệm của Bên A và Bên B trong hợp đồng được phân chia cụ thể ra sao?"`
* `"Quy trình nghiệm thu và điều kiện thanh toán theo từng giai đoạn được quy định thế nào?"`
* `"Các mức phạt vi phạm hợp đồng và bồi thường thiệt hại tối đa được áp dụng là bao nhiêu?"`

### 📝 Nhóm 3: Tra cứu Quy trình Nội bộ Doanh nghiệp
* `"Quy trình phê duyệt hợp đồng thương mại có giá trị trên 500 triệu VNĐ gồm những bước nào?"`
* `"Chính sách bảo hành và cam kết chất lượng dịch vụ (SLA) sau khi bàn giao hệ thống được quy định ra sao?"`

---

## 2. 📊 Data Agent (Phân tích Dữ liệu CSV & Live Dashboard)
*Chuyên trách: Nhận file CSV được kéo thả trực tiếp tại Main Area, thực thi mã Python tự động trong Sandbox để phân tích thống kê và vẽ biểu đồ Plotly / AgGrid tương tác.*

### 📝 Nhóm 1: Thống kê & Phân tích Tổng quan Dữ liệu
* `"Hãy tóm tắt tổng quan file CSV này: Số lượng dòng, số cột, danh sách cột và các chỉ số thống kê cơ bản (Mean, Min, Max)."`
* `"Tính tổng doanh thu và tổng số lượng đơn hàng theo từng tháng trong tập dữ liệu."`
* `"Hãy lọc ra Top 5 sản phẩm có doanh số bán hàng cao nhất và Top 5 sản phẩm có lợi nhuận thấp nhất."`
* `"Cho biết tỷ lệ phần trăm đóng góp doanh thu của từng chi nhánh/khu vực."`

### 📝 Nhóm 2: Trực quan hóa Dữ liệu (Vẽ Biểu đồ Plotly)
* `"Vẽ biểu đồ cột (Bar Chart) thể hiện tổng doanh số bán hàng theo từng khu vực (Region)."`
* `"Tạo biểu đồ đường (Line Chart) biểu diễn xu hướng doanh thu hàng tháng và đường xu hướng trung bình."`
* `"Vẽ biểu đồ tròn (Pie Chart) thể hiện cơ cấu tỷ trọng doanh thu của các nhóm danh mục sản phẩm."`
* `"Vẽ biểu đồ phân tán (Scatter Plot) giữa Chi phí Marketing và Doanh thu để phân tích mối tương quan."`
* `"Vẽ biểu đồ hộp (Box Plot) để kiểm tra các giá trị ngoại lệ (Outliers) của giá trị đơn hàng."`

### 📝 Nhóm 3: Phân tích Nâng cao & Dashboard Tổng hợp
* `"Tạo một Dashboard phân tích toàn diện gồm: Các chỉ số KPI tổng (Total Sales, Total Orders, Average Order Value), biểu đồ doanh thu theo vùng, và bảng dữ liệu AgGrid chi tiết."`
* `"Hãy phân tích xem nhóm khách hàng nào mang lại giá trị cao nhất dựa trên lịch sử mua hàng."`

---

## 3. 🌐 Search Agent (Tìm kiếm Web Thời gian thực)
*Chuyên trách: Sử dụng Tavily API kết hợp Crawl4AI cào dữ liệu Markdown bất đồng bộ để tìm kiếm tin tức, giá cả, thời tiết, sự kiện và xu hướng công nghệ mới nhất trên Internet.*

### 📝 Nhóm 1: Tin tức & Thị trường Thời gian thực
* `"Giá vàng SJC và tỷ giá USD tại Việt Nam hôm nay đang ở mức bao nhiêu?"`
* `"Thời tiết tại Hà Nội và TP. Hồ Chí Minh hôm nay thế nào?"`
* `"Tổng hợp các tin tức kinh tế - tài chính nổi bật nhất tại Việt Nam trong 24 giờ qua."`
* `"Giá xăng dầu trong nước vừa được điều chỉnh như thế nào trong kỳ điều hành mới nhất?"`

### 📝 Nhóm 2: Tìm kiếm Xu hướng Công nghệ & Báo cáo Mới nhất
* `"Các xu hướng phát triển Multi-Agent System và LangGraph trong năm 2026 là gì?"`
* `"So sánh tính năng và hiệu năng giữa LangGraph, AutoGen và CrewAI phiên bản mới nhất."`
* `"Cập nhật các tính năng và cải tiến mới nhất của mô hình OpenAI GPT-4o và Claude 3.5 Sonnet."`

### 📝 Nhóm 3: Nghiên cứu & Trích dẫn Nguồn Chuyên sâu
* `"Tìm kiếm và tóm tắt nội dung chính từ các bài báo nghiên cứu mới nhất về kỹ thuật HyDE RAG."`
* `"Tổng hợp các bài đánh giá về thư viện cào dữ liệu Crawl4AI so với Playwright và BeautifulSoup."`

---

## 💡 MẸO ĐẶT CÂU HỎI (PROMPT ENGINEERING TIPS) TỐI ƯU

1. **Dành cho RAG Agent**:
   * Nên đưa các từ khóa định danh tài liệu vào câu hỏi (ví dụ: *"Theo hợp đồng NDA...", "Trong tài liệu SOW..."*).
   * Đặt câu hỏi cụ thể vào nội dung cần tra cứu thay vì hỏi quá chung chung.

2. **Dành cho Data Agent**:
   * Luôn đảm bảo bạn đã **kéo thả file CSV** vào khung Main Area trước khi gửi câu hỏi.
   * Có thể chỉ định rõ loại biểu đồ mong muốn (như *Bar Chart, Line Chart, Pie Chart, Scatter Plot*).

3. **Dành cho Search Agent**:
   * Kết hợp thêm các cụm từ mốc thời gian như *"hôm nay", "mới nhất 2026", "hiện tại"* để Agent tập trung cào các trang tin tức thời gian thực.
   * SearchAgent sẽ tự động trích dẫn các đường link tham khảo dạng `[Tiêu đề](URL)` ở cuối phản hồi.
