from sqlalchemy import case

from app.modules.drive.models import DriveFile


def test_claim_priority_sql_order():
    order_expr = case(
        (DriveFile.mime_type.like("video/%"), 0),
        else_=1,
    )

    compiled = str(order_expr.compile(compile_kwargs={"literal_binds": True}))
    assert "CASE" in compiled
    assert "video/%" in compiled
