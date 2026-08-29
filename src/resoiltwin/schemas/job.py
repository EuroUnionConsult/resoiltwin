"""Leitura de uma execucao de ingestao, seja qual for a origem que a produziu.

Vive fora de `schemas/eo.py` porque deixou de ser so do satelite: a
sincronizacao meteorologica escreve na MESMA tabela `ingestion_jobs` e e lida
pela MESMA rota `GET /jobs/{id}`. Uma segunda copia desta classe ao lado da
primeira era o caminho para as duas divergirem numa coluna e a mesma linha
passar a ler-se de duas maneiras conforme a rota que a devolvesse.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from resoiltwin.enums import JobStatus


class IngestionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    aoi_id: uuid.UUID
    # `reanalysis_sync`, `ipma_sync` ou `eo_sync`: e o que distingue, no corpo
    # da resposta, qual das ingestoes correu. Sem ele, dois jobs do mesmo sitio
    # e do mesmo dia so se distinguiriam pelo request_hash, que e um digest.
    job_type: str
    # o campo que impede um 202 alegre. Um pedido aceite e processado continua
    # a ser 202 mesmo quando a execucao correu mal -- o que separa o sucesso da
    # falha e este campo, e um cliente que assuma sucesso a partir do codigo
    # HTTP perde a falha de ingestao inteira.
    status: JobStatus
    date_from: date
    date_to: date
    request_hash: str
    # o que este job correu, legivel pela rota. Sem este campo, saber se um
    # job aplicou a mascara ao pixel obrigava a ir a tabela de observacoes --
    # e um job que escreveu zero linhas nao tinha sequer onde ser lido.
    # `None` e o que fica dos jobs anteriores a migracao 0007: "nao
    # registado", nao "sem mascara".
    processing_version: str | None
    started_at: datetime
    finished_at: datetime | None
    rows_written: int
    error: str | None
