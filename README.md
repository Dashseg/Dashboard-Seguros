# Painel Seguros & Saúde

Dashboard público para acompanhar o **tamanho, o crescimento, a sinistralidade e a concentração** do
mercado segurador (SUSEP) e da saúde suplementar (ANS). Os dados são baixados direto das bases abertas
dos dois órgãos por um robô no GitHub Actions, toda semana, e o site é republicado sozinho.

## O que o painel mostra

| Aba | Conteúdo | Fonte |
|---|---|---|
| Visão geral | Prêmios em 12 meses (seguros ex-VGBL, VGBL, PGBL), sinistralidade, beneficiários | SUSEP + ANS |
| Seguros | Prêmio emitido e ganho, sinistralidade e comissionamento por grupo de ramos e por ramo | SUSEP |
| Saúde suplementar | Beneficiários por tipo de contratação, modalidade da operadora e UF | ANS |
| Concentração | Market share, HHI, CR5/CR10 por grupo econômico (seguros) e operadora (saúde) | SUSEP + ANS |

**Definições**

- *Prêmio emitido* = `premio_direto`; *prêmio ganho* = `premio_ganho` (SES, `Ses_seguros.csv`).
- *Sinistralidade* = sinistros ocorridos ÷ prêmio ganho. *Comissionamento* = despesa comercial (`desp_com`) ÷ prêmio ganho.
- Comparações "a/a" usam os 12 meses mais recentes contra os 12 anteriores.
- VGBL é tratado à parte (é acumulação financeira e distorceria o tamanho de "seguros").
- *Beneficiários* = vínculos ativos no mês (`QT_BENEFICIARIO_ATIVO`), base "Informações Consolidadas de Beneficiários" (PDA 024).
- *HHI* = soma dos quadrados das participações (0–10.000): abaixo de 1.500 pouco concentrado; 1.500–2.500 moderado; acima de 2.500 alto.

## Como funciona

```
GitHub Actions (toda terça)          repositório                         GitHub Pages
┌──────────────────────────┐   ┌────────────────────────┐   ┌──────────────────────────┐
│ etl/atualizar.py         │──▶│ data/ans/*.csv.gz      │   │ site/ (HTML + JS + SVG)  │
│  • SUSEP: BaseCompleta   │   │   (cache mensal ANS)   │──▶│ lê site/data/*.json      │
│  • ANS: zips por UF/mês  │──▶│ site/data/*.json       │   │                          │
└──────────────────────────┘   └────────────────────────┘   └──────────────────────────┘
```

- **SUSEP**: baixa o `BaseCompleta.zip` do SES (centenas de MB) e agrega por mês, ramo e grupo econômico.
- **ANS**: baixa um zip por UF por mês (~400 MB/mês). Cada mês é reduzido a um arquivo pequeno em
  `data/ans/`, então as execuções seguintes só baixam meses novos. Na primeira vez o histórico é
  preenchido aos poucos — 6 meses por execução (ajustável) até completar 25 meses.
- Se uma fonte falhar (portal fora do ar, mudança de layout), a outra segue e o site continua mostrando os
  últimos dados bons. O rodapé do painel indica a situação de cada fonte.

## Primeira configuração (uma vez só)

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. **Settings → Actions → General → Workflow permissions: Read and write permissions** → Save.
3. **Actions → Atualizar dados → Run workflow.** A primeira execução leva de 1 a 3 horas.
   Para completar o histórico da ANS mais rápido, rode de novo (ou informe um número maior em
   "Máximo de meses da ANS").
4. O endereço do site aparece em **Settings → Pages** (algo como `https://<usuario>.github.io/<repositorio>/`).

Depois disso, nada a fazer: o robô roda toda terça-feira.

## Ajustes comuns

| Quero… | Onde |
|---|---|
| Mudar o dia/horário da atualização | `cron` em `.github/workflows/atualizar-dados.yml` |
| Mais/menos histórico da ANS | variável `ANS_MESES_HISTORICO` (padrão 25) |
| Histórico SUSEP desde outro ano | variável `SUSEP_ANO_INICIO` (padrão 2014) |
| Atualizar na hora | Actions → Atualizar dados → Run workflow |

## Rodar localmente (opcional)

```bash
pip install -r etl/requirements.txt
python etl/atualizar.py            # baixa as bases reais (demora)
cd site && python -m http.server   # abre http://localhost:8000
```

Para testar o código sem baixar nada, gere bases simuladas com o mesmo layout:

```bash
python tests/gerar_dados_teste.py /tmp/teste
SUSEP_ZIP=/tmp/teste/BaseCompleta.zip ANS_DIR=/tmp/teste/ans python etl/atualizar.py
```

> Os números simulados são aleatórios. Não faça commit de `site/data/` gerado em teste.

## Fontes

- SUSEP — Sistema de Estatísticas (SES): https://www2.susep.gov.br/menuestatistica/ses/
- ANS — Dados Abertos, Informações Consolidadas de Beneficiários:
  https://dadosabertos.ans.gov.br/FTP/PDA/informacoes_consolidadas_de_beneficiarios-024/

Dados públicos, sujeitos a recargas pelos órgãos.
