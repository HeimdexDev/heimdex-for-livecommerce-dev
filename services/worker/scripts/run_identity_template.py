import sys
from pathlib import Path
from typing import List, Optional

import typer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.faces.register import build_identity_template

app = typer.Typer(add_completion=False)


@app.command()
def run(
    identity_id: str = typer.Option(..., help="Identity ID to register"),
    ref_image: List[str] = typer.Option([], help="Reference image path (repeatable)"),
    ref_dir: Optional[str] = typer.Option(None, help="Directory with reference images"),
    out: Optional[str] = typer.Option(None, help="Output json path"),
    det_size: int = typer.Option(640, help="SCRFD det_size (pixels)"),
    ctx_id: int = typer.Option(-1, help="SCRFD ctx_id (-1=CPU, 0=GPU)"),
    exemplars_k: int = typer.Option(5, help="Number of exemplar embeddings to store"),
):
    out_path = build_identity_template(
        identity_id=identity_id,
        ref_images=ref_image,
        ref_dir=ref_dir,
        out_path=out,
        det_size=det_size,
        ctx_id=ctx_id,
        exemplars_k=exemplars_k,
    )
    print(f"[OK] Identity template written to {out_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        sys.argv.pop(1)
    app()
