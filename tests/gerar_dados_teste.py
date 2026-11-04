"""Gera arquivos SIMULADOS com o mesmo layout das bases reais, para testar o robô offline.

    python tests/gerar_dados_teste.py /tmp/teste
    SUSEP_ZIP=/tmp/teste/BaseCompleta.zip ANS_DIR=/tmp/teste/ans python etl/atualizar.py

Os números são aleatórios — servem só para validar o código, nunca para análise.
"""
import io
import random
import sys
import zipfile
from pathlib import Path

random.seed(7)
saida = Path(sys.argv[1] if len(sys.argv) > 1 else "teste")
saida.mkdir(parents=True, exist_ok=True)


def br(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


# ------------------------------------------------------------------ SUSEP
ramos = [("0531", "0531 - Automóvel - Casco", "05"), ("0553", "RCF-V", "05"), ("0114", "Compreensivo Residencial", "01"),
         ("0118", "Compreensivo Empresarial", "01"), ("0977", "Prestamista", "09"), ("0993", "Vida em Grupo", "09"),
         ("1391", "Vida Individual", "13"), ("1102", "Agrícola com cobertura do FESR", "11"),
         ("0775", "Garantia Segurado - Setor Público", "07"), ("0351", "RC Geral", "03"), ("0621", "Transporte Nacional", "06")]
grupos_ramo = {"01": "PATRIMONIAL", "03": "RESPONSABILIDADES", "05": "AUTOMÓVEL", "06": "TRANSPORTES",
               "07": "RISCOS FINANCEIROS", "09": "PESSOAS COLETIVO", "11": "RURAL", "13": "PESSOAS INDIVIDUAL"}
cias = [(str(1000 + i), f"SEGURADORA EXEMPLO {i}", str(i % 9), f"GRUPO EXEMPLO {chr(65 + i % 9)}") for i in range(30)]

linhas = ["damesano;coenti;cogrupo;coramo;premio_direto;premio_de_seguros;premio_retido;premio_ganho;"
          "sinistro_direto;sinistro_retido;sinistro_ocorrido;desp_com;premio_emitido2"]
for ano in range(2019, 2027):
    for mes in range(1, 13):
        if ano == 2026 and mes > 7:
            break
        fator = 1 + (ano - 2019) * 0.09 + mes * 0.004
        for coenti, _, cog, _ in cias:
            peso = 1 / (1 + int(coenti) - 1000) ** 0.8
            for cod, _, _ in ramos:
                if random.random() < 0.35:
                    continue
                p = 9e8 * peso * fator * random.uniform(0.5, 1.5)
                pg = p * random.uniform(0.9, 1.0)
                so = pg * random.uniform(0.3, 0.75)
                dc = pg * random.uniform(0.1, 0.3)
                linhas.append(f"{ano}{mes:02d};{coenti};{cog};{cod};{br(p)};{br(p)};{br(p*.8)};{br(pg)};0;{br(so*.9)};{br(so)};{br(dc)};{br(p)}")

with zipfile.ZipFile(saida / "BaseCompleta.zip", "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("Ses_seguros.csv", "\n".join(linhas).encode("latin-1"))
    z.writestr("Ses_cias.csv", ("Coenti;Noenti;Cogrupo;Nogrupo\n" + "\n".join(f"{c[0]};{c[1]};;" for c in cias)).encode("latin-1"))
    z.writestr("Ses_ramos.csv", ("coramo;noramo\n" + "\n".join(f"{c};{n}" for c, n, _ in ramos)).encode("latin-1"))
    z.writestr("Ses_gruposramos.csv", ("GRAID;GRANOME;GRACODIGO\n" + "\n".join(f"{i};{c} - {n.title()};{c}" for i, (c, n) in enumerate(grupos_ramo.items()))).encode("latin-1"))
    ge = ["damesano;coenti;noenti;cogrupo;nogrupo"] + [f"202501;{c[0]};{c[1]};{c[2]};{c[3]}" for c in cias]
    z.writestr("Ses_grupos_economicos.csv", "\n".join(ge).encode("latin-1"))
    cb = ["coenti;damesano;tipoProd;contrib;benef"] + [f"{c[0]};{a}{m:02d};{t};{br(random.uniform(1e8, 9e8) * (8 if t == 'VGBL' else 1))};0"
          for c in cias[:12] for a in range(2021, 2027) for m in range(1, 13) for t in ("VGBL", "PGBL", "PrevTrad") if not (a == 2026 and m > 7)]
    z.writestr("Ses_Contrib_Benef.csv", "\n".join(cb).encode("latin-1"))
    cap = ["COENTI;DAMESANO;UF;PREMIO;RESGPAGO;SORTPAGO;NUMPARTIC;RESGATANTES;SORTEIOS"] + [f"{c[0]};{a}{m:02d};SP;{br(random.uniform(1e8, 5e8))};0;0;0;0;0"
          for c in cias[:6] for a in range(2021, 2027) for m in range(1, 13) if not (a == 2026 and m > 7)]
    z.writestr("ses_cap_uf.csv", "\n".join(cap).encode("latin-1"))
    pg = ["coenti;damesano;contribuicoes"] + [f"1001;{a}{m:02d};{br(1.5e9*(1+(a-2019)*.07))}" for a in range(2019, 2027) for m in range(1, 13) if not (a == 2026 and m > 7)]
    z.writestr("ses_pgbl_contrib.csv", "\n".join(pg).encode("latin-1"))
print("SUSEP ok:", len(linhas) - 1, "linhas")

# ------------------------------------------------------------------ ANS
cab = ("#ID_CMPT_MOVEL;CD_OPERADORA;NM_RAZAO_SOCIAL;NR_CNPJ;MODALIDADE_OPERADORA;SG_UF;CD_MUNICIPIO;NM_MUNICIPIO;TP_SEXO;"
       "DE_FAIXA_ETARIA;DE_FAIXA_ETARIA_REAJ;CD_PLANO;TP_VIGENCIA_PLANO;DE_CONTRATACAO_PLANO;DE_SEGMENTACAO_PLANO;"
       "DE_ABRG_GEOGRAFICA_PLANO;COBERTURA_ASSIST_PLAN;TIPO_VINCULO;QT_BENEFICIARIO_ATIVO;QT_BENEFICIARIO_ADERIDO;"
       "QT_BENEFICIARIO_CANCELADO;DT_CARGA").replace("#", "")
mods = ["Medicina de Grupo", "Cooperativa Médica", "Seguradora Especializada em Saúde", "Autogestão", "Odontologia de Grupo", "Filantropia"]
contrs = ["Coletivo empresarial", "Coletivo por adesão", "Individual ou familiar"]
ops = [(str(300000 + i * 37), f"OPERADORA EXEMPLO {i} S.A.", mods[i % len(mods)]) for i in range(40)]
ufs = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE",
       "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
pesos_uf = {"SP": 12, "RJ": 4, "MG": 4, "PR": 2, "RS": 2}
meses = [202407 + i for i in range(6)] + [202501 + i for i in range(12)] + [202601 + i for i in range(8)]
for m in meses:
    pasta = saida / "ans" / str(m)
    pasta.mkdir(parents=True, exist_ok=True)
    cresc = 1 + (meses.index(m)) * 0.003
    for uf in ufs:
        rows = [cab]
        for op, nome, mod in ops:
            if random.random() < 0.4:
                continue
            for contr in contrs:
                cob = "Odontológico" if "Odonto" in mod else random.choice(["Médico-hospitalar", "Médico-hospitalar", "Odontológico"])
                q = int(4000 * pesos_uf.get(uf, 0.5) * cresc * random.uniform(.3, 1.7) / (1 + ops.index((op, nome, mod)) * .15))
                rows.append(f"{m//100}-{m%100:02d};{op};{nome};00000000000100;{mod};{uf};3550308;MUNICIPIO;F;30 a 39 anos;;123;P;{contr};"
                            f"Ambulatorial;Nacional;{cob};Titular;{q};0;0;2026-10-01")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"pda-024-icb-{uf}-{m//100}_{m%100:02d}.csv", "\n".join(rows).encode("utf-8"))
        (pasta / f"pda-024-icb-{uf}-{m//100}_{m%100:02d}.zip").write_bytes(buf.getvalue())
print("ANS ok:", len(meses), "meses")
