from pydantic import BaseModel

class KPI(BaseModel):
    total_reads: int
    pending: int
    verified: int
    auto_master: int
    master_total: int
    mlpr_total: int
    alpr_total: int
