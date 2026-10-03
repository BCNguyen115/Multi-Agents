"""What leaves for the trace server: personal data is masked, structure and numbers stay."""
from src.shared.tracing import mask_pii


def test_phone_email_card_and_citizen_id_are_masked_anywhere_in_the_payload():
    payload = {
        "input": {"messages": [{"role": "user", "content": "Gọi 0912345678 hoặc mail an.nguyen@example.com, CCCD 012345678901"}]},
        "tags": ["rag", "the card 4111 1111 1111 1111"],
        "count": 3,
    }
    masked = mask_pii(payload)
    text = str(masked)
    for secret in ("0912345678", "an.nguyen@example.com", "012345678901", "4111 1111 1111 1111"):
        assert secret not in text
    assert masked["count"] == 3 and masked["input"]["messages"][0]["role"] == "user"  # shape and non-strings untouched


def test_text_without_personal_data_passes_unchanged():
    assert mask_pii("Doanh thu quý 3 tăng 12,5%") == "Doanh thu quý 3 tăng 12,5%"
