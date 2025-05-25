import re

def format_lists_to_html(text: str) -> str:
    import re

    def numbered(match):
        items = match.group(0).splitlines()
        items = [re.sub(r'^\s*\d+\.\s*', '', i).strip() for i in items if i.strip()]
        return '<ol class="list-decimal ml-5">' + ''.join(f'<li class="mb-2">{i}</li>' for i in items) + '</ol>'

    def bulleted(match):
        items = match.group(0).splitlines()
        items = [re.sub(r'^\s*-\s*', '', i).strip() for i in items if i.strip()]
        return '<ul class="list-disc ml-5">' + ''.join(f'<li class="mb-2">{i}</li>' for i in items) + '</ul>'

    text = re.sub(r'((?:^\s*\d+\..+\n?)+)', numbered, text, flags=re.MULTILINE)
    text = re.sub(r'((?:^\s*-\s.+\n?)+)', bulleted, text, flags=re.MULTILINE)
    return text

def fix_numbering(text):
    # Detektira sve linije koje izgledaju kao "1. nešto"
    lines = text.split("\n")
    fixed_lines = []
    counter = 1
    for line in lines:
        if re.match(r"^\s*1\.\s", line):
            line = re.sub(r"^\s*\d+\.\s", f"{counter}. ", line)
            counter += 1
        elif re.match(r"^\s*\d+\.\s", line):
            line = re.sub(r"^\s*\d+\.\s", f"{counter}. ", line)
            counter += 1
        fixed_lines.append(line)
    return "\n".join(fixed_lines)