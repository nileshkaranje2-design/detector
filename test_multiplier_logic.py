import re

def detect_multiplier(ocr_text: str) -> str | None:
    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    flew_away_idx = -1
    for i, line in enumerate(lines):
        if "FLEW AWAY" in line.upper():
            flew_away_idx = i
            break
            
    if flew_away_idx != -1 and flew_away_idx + 1 < len(lines):
        # The multiplier is usually on the next line or the one after
        for j in range(flew_away_idx + 1, min(flew_away_idx + 3, len(lines))):
            match = re.search(r'(\d+\.\d+)x?', lines[j], re.IGNORECASE)
            if match:
                return match.group(1) + "x"
    return None

test_text1 = "FLEW AWAY!\n1.27x\nsomething else"
test_text2 = "Some random text\nFLEW AWAY\n2.5x\nFooter"

print(detect_multiplier(test_text1))
print(detect_multiplier(test_text2))
