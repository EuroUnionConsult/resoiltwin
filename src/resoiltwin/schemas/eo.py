from datetime import date

from pydantic import BaseModel, Field, model_validator


class EoSyncRequest(BaseModel):
    aoi_code: str = Field(pattern=r"^[A-Z0-9-]{3,64}$")
    date_from: date
    date_to: date
    # mascara SCL ao pixel, ligada por omissao: quem nao escolher fica com o
    # comportamento correcto. `false` reproduz o evalscript v1, que produziu as
    # series que ja estao gravadas -- e para repetir o passado, nao o caminho
    # normal. O tipo e bool a serio: uma string a passar por verdadeira
    # escolhia o script errado sem ninguem dar por isso.
    scl_mask: bool = True

    @model_validator(mode="after")
    def _janela_coerente(self):
        # recusar aqui, com 422, e mais barato do que criar um job so para
        # ele falhar na Statistical API por uma janela invertida.
        if self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self
