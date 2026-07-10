"""Barra de progreso para qa.execute."""

import sys

BAR_WIDTH = 30


def show_progress(done: int, total: int) -> str:
    """Renderiza y escribe barra de progreso a stderr."""
    pct = int((done / total) * 100) if total > 0 else 0
    filled = int(BAR_WIDTH * done / total) if total > 0 else 0
    bar = '█' * filled + '░' * (BAR_WIDTH - filled)
    line = f'\r[{bar}] {pct}% ({done}/{total})   '
    sys.stderr.write(line)
    sys.stderr.flush()
    return line
