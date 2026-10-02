# RAG Agent — review và các sửa đổi

Tài liệu này ghi lại các lỗi tìm thấy khi review sâu RAG Agent, cách sửa, và số đo thực tế. Số đo lấy từ `python -m scripts.run_rag_eval` trên kho thật (≈2.000 chunk, 60 câu hỏi có đáp án + 12 câu ngoài phạm vi); chi tiết ở `reports/rag_eval.md`.

## 1. Lỗi chính và cách sửa

| Nhóm | Vấn đề | Sửa |
|---|---|---|
| An toàn | Nguồn được đưa vào prompt trong "phong bì" có thể bị thoát bằng `<<<`/`>>>`; nhãn header từ dữ liệu chưa được làm sạch | Trung hoà `<<<`/`>>>`, làm sạch nhãn; chỉ loại chunk khi có tín hiệu injection mạnh (`_looks_like_injection`) |
| Đúng đắn | Lỗi/kết quả rỗng vẫn được đưa cho LLM; câu trả lời không có trích dẫn | Không gọi LLM khi lỗi/rỗng; bắt buộc `[n]`; API trả `cite/page/snippet` cho `SourcesList` |
| Hội thoại | Câu hỏi nối tiếp ("còn điều khoản đó thì sao?") tìm kiếm không có ngữ cảnh; stream không lưu lượt | Viết lại câu hỏi từ lịch sử Redis; `/api/chat/stream` lưu lượt |
| Verifier | LLM chấm lại câu trả lời RAG (chậm, không ổn định) | Xác minh tất định: có trích dẫn? con số có trong nguồn? → `verification{…}`; orchestrator `_rag_verdict`; giữ JSON hợp lệ khi hết lượt retry (`_annotate_unverified`) |
| Truy xuất | Chỉ vector; index trùng (ivfflat + hnsw); full-text tính lại mỗi truy vấn | Hybrid vector + FTS hợp nhất bằng RRF, cột `tsv` sinh sẵn + GIN, bỏ index thừa, lọc theo category, cổng similarity |
| Rerank | Timeout 30 s làm treo phản hồi; circuit breaker không tự phục hồi; cắt văn bản thô | Ngân sách tổng `RERANKER_TIMEOUT`, half-open sau lỗi, pool và độ dài văn bản cấu hình được |
| Nạp dữ liệu | Nạp lại toàn bộ mỗi lần; dedup toàn cục; trang PDF mất; header/footer lặp lại thành nhiễu | Nạp tăng dần theo hash, thay tài liệu nguyên tử, dedup theo tài liệu (0.95), ánh xạ trang, cắt header/footer |
| Đánh giá | Số liệu "keyword" bị gọi là độ chính xác | Đổi tên `keyword_coverage`; thêm `run_rag_eval` (hit@k, MRR, từ chối, hỗ trợ câu trả lời) |

## 2. Lỗi "RAG chưa hoạt động" (ảnh + log của người dùng)

- Câu hỏi chung ("Tra cứu điều khoản hợp đồng & chính sách nội bộ") bị trả `Tôi không tìm thấy…`: prompt cho phép `NOT_FOUND` quá dễ. Nay chủ đề rộng → tóm tắt có trích dẫn; `NOT_FOUND` chỉ khi nguồn hoàn toàn không liên quan.
- 37/1.971 chunk bị lọc nhầm là injection vì khớp mẫu "Persona Hijack" yếu → chỉ bỏ khi có tín hiệu mạnh.
- `.env` của người dùng ghi đè `RERANKER_TIMEOUT=30`, `HYBRID_CANDIDATES_K=10`, `MAX_RERANK_TEXT_LENGTH=500` → đã xoá ba khoá để dùng mặc định đã đo.
- Data agent: 14/14 lần LLM viết lại story bị từ chối vì yêu cầu giữ cả mã enum nội bộ (`up`, `month`, `sum`…) → chỉ giữ tên thật từ dữ liệu (`_dataset_names`).
- Cảnh báo title timeout nay ghi rõ loại lỗi thay vì chuỗi rỗng.
- Phát hiện khi chạy end-to-end qua backend thật:
  - Câu hỏi nối tiếp ("Còn thời hạn bảo mật thì sao?") trả "không tìm thấy" 4/4 lần: khi câu hỏi nêu loại tài liệu (NDA), tìm kiếm bị giới hạn cứng trong category đó và chỉ mở rộng nếu category trả về 0 dòng. Nay nếu lần thử trong category kết thúc bằng NOT_FOUND thì thử lại một lần trên toàn kho (bỏ qua nếu ra đúng các chunk cũ). Log thật xác nhận: `scope=['nda']` rồi `scope=all`.
  - Phản hồi `/api/chat` bị treo tới hàng giờ khi OpenRouter chậm/mất kết nối vì việc lưu bộ nhớ dài hạn (mem0 gọi LLM) được `await` trước khi trả lời. Bản sửa đầu tiên (tác vụ nền + `wait_for` 30 s) **chưa đủ**: mem0 là đồng bộ nên vẫn chặn event loop 2–11 s và timeout không ngắt được. Nay các lời gọi mem0 chạy trong thread (`asyncio.to_thread`) với timeout thật (ghi 30 s, đọc 5 s), ở cả `/api/chat` và stream; xem `docs/PROJECT_REVIEW_AND_ROADMAP.md` mục 3.

## 3. Số đo (kho thật, CPU)

| Cấu hình | hit@1 | hit@5 | MRR | Độ trễ trung vị |
|---|---|---|---|---|
| Vector `raw` | 0.267 | 0.517 | 0.381 | – |
| Vector `hyde` | 0.283 | 0.500 | 0.395 | – |
| `both` (mặc định) + FTS + RRF | 0.333 | 0.583 | 0.443 | – |
| + rerank 500 ký tự | 0.467 | 0.600 | 0.531 | 2.4 s |
| + rerank 1000 ký tự (mặc định) | 0.517 | 0.667 | 0.583 | 4.2 s |
| + rerank 2000 ký tự | 0.500 | 0.700 | 0.582 | 6.7 s |

Mặc định được chọn: `RERANK_POOL_K=10`, `MAX_RERANK_TEXT_LENGTH=1000`, `RERANKER_TIMEOUT=8.0` (trung vị 4.2 s nằm gọn trong ngân sách), `RAG_MIN_VECTOR_SCORE=0.30` (xem mục 4).

Chất lượng câu trả lời (20 câu có đáp án, rerank bật, sau khi sửa prompt): 18/20 được trả lời (trước đó 15/20), 100% có trích dẫn, 100% con số có trong nguồn, LLM chấm mức hỗ trợ trung bình 0.78 (trước đó 0.67), từ chối đúng 12/12 câu ngoài phạm vi.

Sau vòng tối ưu (30 câu ngẫu nhiên từ bộ 75 câu, gồm câu viết tay): 28/30 được trả lời, 100% có trích dẫn, 100% con số có trong nguồn, mức hỗ trợ do LLM chấm 0.66 (mẫu khác và lớn hơn nên không so trực tiếp với 0.78), từ chối đúng 12/12. Rerank một tầng: hit@1 0.453 so với 0.307 khi không rerank, MRR 0.531 so với 0.412, 4.2 s.

## 4. Vòng tối ưu theo đề xuất (mỗi thay đổi được đo trên kho thật)

Nguyên tắc: mỗi hướng tối ưu chỉ được giữ nếu số đo (`scripts/run_rag_eval.py`) cho thấy lợi ích. Bộ đo gồm 60 câu sinh từ kho (một nửa tiếng Việt) và 15 câu tiếng Việt viết tay trong `dataset/rag_eval_manual.json` (đáp án = chunk của đúng tài liệu chứa một cụm từ; 3 câu là câu nối tiếp có lịch sử hội thoại). 75 câu có đáp án + 12 câu ngoài phạm vi.

| # | Hướng | Kết quả đo | Quyết định |
|---|---|---|---|
| 1+4 | Planner: 1 lần gọi LLM cho ra câu hỏi độc lập + đoạn HyDE (thay cho 2 lần gọi nối tiếp) | MRR 0.443 so với 0.444 của đường cũ (ngang nhau; tiếng Việt 0.461 so với 0.446). Câu nối tiếp: hit@5 0% khi không viết lại, 67% với planner (chỉ 3 câu, mới là dấu hiệu). Median 2.8 s | **Giữ** (đỡ một lần gọi LLM cho câu nối tiếp) |
| 1 | Dịch câu hỏi sang tiếng Anh cho embedding + từ khoá FTS | MRR 0.396 so với 0.440; câu tiếng Việt vốn đã ngang câu tiếng Anh (0.446 so với 0.434) | **Bỏ**: mô hình embedding xử lý tiếng Việt tốt; giả thuyết "lỗi do khác ngôn ngữ" sai |
| 2 | Rerank pool 20 | MRR 0.557 so với 0.542 (+0.015) nhưng 7.8 s so với 4.2 s | Bỏ (vượt ngân sách 8 s) |
| 2 | Rerank hai tầng (sàng 20 ứng viên bằng 300–400 ký tự đầu, chấm lại 5–6 bằng 1000 ký tự) | MRR 0.493 và 0.414, kém hơn một tầng (0.542); 5.4–6.6 s | **Bỏ**: đoạn đầu chunk chủ yếu là tiêu đề, không đủ để sàng |
| 2 | Rerank bằng câu tiếng Anh | MRR 0.543 so với 0.539 | Bỏ (không khác) |
| 3 | Tối đa 2 chunk / tài liệu | hit@5 0.617 so với 0.650 | **Bỏ** (kém hơn) |
| 3 | Thêm chunk trước/sau của top-N vào ngữ cảnh | hit@5 0.650 → 0.650 (top 2 hoặc 3) | **Bỏ** (không tăng, tốn thêm truy vấn và token) |
| 5 | Ngưỡng từ chối theo điểm reranker | Điểm reranker thấp và rộng trên kho này (câu có đáp án: nhiều câu gần 0); ngưỡng 0.1 loại nhầm 40% câu hợp lệ | **Bỏ** |
| 5 | Ngưỡng cosine (điểm vector tốt nhất) | Sau khi planner giữ đúng ngôn ngữ: câu ngoài phạm vi tối đa 0.286, câu có đáp án tối thiểu 0.358 → tách hoàn toàn ở 0.30–0.35 | Đặt `RAG_MIN_VECTOR_SCORE=0.30` |
| 6 | Dedup chéo tài liệu | Không có cặp chunk nào giữa hai tài liệu có độ tương tự ≥ 0.90 (lớn nhất 0.88, trung vị 0.71) | **Bỏ**: nhận định "biểu mẫu SEC gần trùng" là sai |
| 7 | Bộ đo tốt hơn | Số đo theo ngôn ngữ và theo câu nối tiếp, bộ câu hỏi viết tay, cổng CI (`--min-hit5`, `--min-mrr`, `--gate-on`) | Đã làm |
| 8 | Contextual retrieval (`KB_LLM_CONTEXT`): một câu ngữ cảnh do LLM viết, đặt đầu `content` rồi embedding lại toàn kho trong DB scratch | Chế độ `plan`: hit@5 0.520 so với 0.587, MRR 0.386 so với 0.443; có rerank (`single10`): hit@5 0.600 so với 0.653, MRR 0.492 so với 0.531 (cùng 75 câu, cùng bộ đo). Kém hơn ở mọi chỉ số, cả tiếng Việt lẫn tiếng Anh; chỉ câu nối tiếp hit@5 0.333 so với 0.667 | **Không bật** (mặc định `KB_LLM_CONTEXT=false`). Chưa kiểm chứng nguyên nhân (có thể câu ngữ cảnh làm các chunk cùng loại hợp đồng giống nhau hơn); câu nối tiếp chỉ có 3 câu nên không đủ kết luận. Tính năng giữ lại để thử với kho khác |

Hai lỗi do chính vòng tối ưu gây ra, phát hiện khi chạy end-to-end qua backend thật và đã sửa: (a) planner dịch câu hỏi tiếng Việt sang tiếng Anh dù prompt yêu cầu giữ ngôn ngữ → câu trả lời bằng tiếng Anh và ngưỡng cosine lỏng hơn; nay prompt ép giữ nguyên ngôn ngữ và agent trả lời theo đúng câu người dùng gõ (bản viết lại chỉ là ngữ cảnh); (b) bộ kiểm tra số coi "Sources 1, 3 and 4" trong câu trả lời là con số cần chứng minh → nay bỏ qua số thứ tự nguồn.

Về "17% câu không lọt top 20": không phải do ngôn ngữ (bước 1) hay do trùng lặp (bước 6). 10 câu trượt có chunk kết quả giống chunk đúng ở mức 0.6–0.85, tức là nội dung khác thật. Với kho toàn hợp đồng cùng thể loại, một câu hỏi sinh từ một chunk thường khớp với nhiều chunk tương tự ở tài liệu khác, nên trần hit@20 ≈ 0.83 một phần phản ánh giới hạn của tiêu chí "đúng chunk gốc", không hoàn toàn là lỗi truy xuất.

Bài học về phép đo: lượt đo hai tầng đầu tiên bị sai vì 20 ứng viên × 1000 ký tự vượt ngân sách 8 s, timeout ba lần làm cầu dao mở và các preset sau không hề gọi reranker (độ trễ 0.0 s). Bộ đo nay nới timeout, đặt lại cầu dao mỗi preset và cảnh báo khi một preset không tới được reranker.

## 5. Giới hạn đã biết

- Rerank trên CPU mất vài giây; GPU hoặc pool nhỏ hơn sẽ nhanh hơn (đánh đổi MRR).
- `rag_chunks` cũ được migrate tự động lúc backend khởi động, nhưng `doc_hash`/`page` chỉ có sau `python -m scripts.run_ingestion --reset` (tốn chi phí embedding cho ≈2.000 chunk).
- Tenant: `RAG_TENANT_IDS` mới là hook, chưa gắn với danh tính thật ở gateway.
- Bộ câu hỏi đánh giá được sinh từ chính kho; nên bổ sung câu hỏi do người thật viết.
