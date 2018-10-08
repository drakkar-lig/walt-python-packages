import re

RE_HEADER_SEP_LINE = re.compile("-+:? *[|] *:?-+")
ALIGN_LEFT = -1
ALIGN_CENTER = 0
ALIGN_RIGHT = 1

def detect_table(buf):
    return RE_HEADER_SEP_LINE.search(buf) is not None

def analyse_table(buf):
    lines = buf.splitlines()
    for idx, line in enumerate(lines):
        if RE_HEADER_SEP_LINE.search(line):
            header_idx = idx
            header_sep_line = line
            break
    alignments = []
    for sep in header_sep_line.strip().strip('|').split('|'):
        sep = sep.strip()
        aligndef = (sep.startswith(':'), sep.endswith(':'))
        alignments.append({
            (False, False): ALIGN_LEFT,
            (True, False): ALIGN_LEFT,
            (True, True): ALIGN_CENTER,
            (False, True): ALIGN_RIGHT
        }[aligndef])
    num_cols = len(alignments)
    table_content = []
    for idx, line in enumerate(lines):
        if idx == header_idx:
            continue
        if line.strip() == '':
            continue
        row = [ cell.strip() for cell in line.strip().strip('|').split('|') ]
        row = row[:num_cols]
        row += [''] * (num_cols - len(row))
        table_content.append(row)
    return table_content, alignments

def align(text, real_text_len, field_len, alignment):
    if alignment == ALIGN_LEFT:
        return text + ' ' * (field_len - real_text_len)
    elif alignment == ALIGN_RIGHT:
        return ' ' * (field_len - real_text_len) + text
    else:   # center
        left_len = (field_len - real_text_len)/2
        right_len = field_len - real_text_len - left_len
        return ' ' * left_len + text + ' ' * right_len

def horizontal_line(col_widths, left_char, sep_char, right_char):
    return left_char + sep_char.join(u'\u2500' * (w+2) for w in col_widths) + right_char + '\n'

def render_table(md_renderer, buf):
    table_content, alignments = analyse_table(buf)
    col_widths = [ max(md_renderer.real_text_len(cell) for cell in col) \
            for col in zip(*table_content) ]
    # print top line
    md_renderer.lit(horizontal_line(col_widths, u'\u250c', u'\u252c', u'\u2510'))
    # print header
    for col_idx, word in enumerate(table_content[0]):
        md_renderer.lit(u'\u2502 ')
        md_renderer.stack_context(bold = True)
        md_renderer.lit(align(word, md_renderer.real_text_len(word), col_widths[col_idx], ALIGN_CENTER))
        md_renderer.pop_context()
        md_renderer.lit(' ')
    md_renderer.lit(u'\u2502\n')
    # print value rows
    separation_line = horizontal_line(col_widths, u'\u251c', u'\u253c', u'\u2524')
    for row_idx, row in enumerate(table_content[1:]):
        md_renderer.lit(separation_line)
        for col_idx, word in enumerate(row):
            md_renderer.lit(u'\u2502 ')
            md_renderer.lit(align(word, md_renderer.real_text_len(word), col_widths[col_idx], alignments[col_idx]))
            md_renderer.lit(' ')
        md_renderer.lit(u'\u2502\n')
    # print bottom line
    md_renderer.lit(horizontal_line(col_widths, u'\u2514', u'\u2534', u'\u2518'))
