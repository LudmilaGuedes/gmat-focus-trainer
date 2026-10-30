# Banco de conteúdo de exemplo

Este diretório é o banco de conteúdo **público** do GMAT Focus Trainer: um recorte pequeno de questões e lições
**originais**, escritas para demonstrar o app (16 assuntos das 3 seções, os 6 tipos de questão e os 5 níveis).

O app lê o banco da pasta definida em `config.py`:

1. `GMAT_CONTENT_DIR`, se a variável de ambiente estiver definida;
2. senão `sample_bank/`, se existir — é onde fica um banco pessoal maior, **fora do git** (`.gitignore`);
3. senão este `sample_bank/`.

Os dois bancos usam exatamente o mesmo formato, descrito abaixo. Material oficial do GMAT (GMAC/Official Guide) ou
de cursos pagos tem direitos autorais: se você cadastrar esse tipo de questão para uso próprio, faça isso só no banco
pessoal, nunca aqui.

## Fluxo de trabalho

1. Editar os arquivos YAML (`taxonomy_seed.yaml`, `study_plan.yaml`, `lessons/*.yaml`, `questions/**/*.yaml`).
2. Rodar, na raiz do projeto (com o venv ativado): `python scripts/init_db.py` (idempotente: atualiza pelo `slug`/`code`,
   nunca duplica).
3. Rodar `pytest tests/test_content_bank.py` (valida formato, confere respostas numéricas, equilíbrio de gabaritos).

## Estrutura de pastas

```
sample_bank/
  taxonomy_seed.yaml              # árvore Seção -> Conteúdo -> Subtópico
  study_plan.yaml                 # ordem da trilha (blocos de subtópicos)
  lessons/*.yaml                  # 1 lição completa por subtópico + flashcards
  questions/
    quantitative_reasoning/*.yaml
    verbal_reasoning/*.yaml
    data_insights/*.yaml
```

Um arquivo de questões cobre tipicamente **um content_area**, mas pode misturar subtópicos e
níveis de dificuldade diferentes dentro dele — o import não exige 1 arquivo = 1 subtópico.

## Schema de uma questão (`questions/**/*.yaml`)

```yaml
questions:
  - slug: qr-algebra-easy-1        # ID estável e único — nunca reutilize nem mude depois de curado
    subtopic: qr_algebra_linear_equations   # code de um Subtopic já existente em taxonomy_seed.yaml
    question_type: multiple_choice   # ver "Tipos de questão" abaixo
    difficulty: 3                    # 1..5 (N1 Fundamentos ... N5 Expert) — ver "Níveis" abaixo
    stem: |
      Enunciado da questão aqui.
    stimulus: |                      # opcional — texto extra acima do enunciado (ex.: as 2
      Texto de apoio opcional.       # afirmações de Data Sufficiency, um parágrafo curto)
    media: null                      # opcional — ver "Tipos de questão" para o formato por tipo
    options:
      - { label: A, text: "...", correct: false }
      - { label: B, text: "...", correct: true }
      - { label: C, text: "...", correct: false }
      - { label: D, text: "...", correct: false }
      - { label: E, text: "...", correct: false }
    explanation: |
      Explicação completa — sempre exibida ao usuário em "ver solução", acerte ou erre.
    source: original                 # original | official (questão oficial que você possui) | external
    source_ref: null                 # opcional: de onde veio, ex. "OG 2024-25, PS #112"
    answer_check: "12**2 - 2*32"     # opcional (recomendado em Quant): expressão Python que deve dar o
                                     # valor da alternativa correta; conferida por tests/test_content_bank.py
                                     # (sem builtins: round/max não existem; use math.*, comb, Fraction…)
    status: active                   # active | draft (não é servida) | retired (não é servida)
    author: null                     # opcional, seu nome/iniciais se quiser rastrear autoria
```

Campos obrigatórios: `slug`, `subtopic`, `question_type`, `difficulty`, `stem`, `options`
(exatamente uma alternativa `correct: true` por grupo), `explanation`.

Formatação: `x^2` vira sobrescrito, `sqrt(` vira `√(` e `**trecho**` vira negrito (use nas questões de
boldface de Critical Reasoning). Linhas quebradas no YAML são unidas em parágrafos; linha em branco = novo
parágrafo; linhas começando com `I.`, `II.`, `(1)` ficam em linha própria.

## Níveis (`difficulty`)

Cada nível corresponde a uma faixa real de nota (ver `app/levels.py`); escreva a questão pensando em
"quem acerta esta questão com ~60-70% de chance?":

| Nível | Faixa | Exemplo de dificuldade |
|---|---|---|
| 1 | até ~455 | conta direta, um passo |
| 2 | ~455-555 | questão fácil da prova real |
| 3 | ~555-645 | questão média; dois passos ou uma armadilha |
| 4 | ~645-705 | médio-difícil; vários passos, alternativas-armadilha fortes |
| 5 | 705+ | as mais difíceis: raciocínio abstrato, casos-limite |

## Questões oficiais que você possui

Se você tem o Official Guide ou outro material oficial, pode cadastrar essas questões **no banco pessoal**
(`content_bank/`, ignorado pelo git) para usar a revisão espaçada e as estatísticas: use `source: official` e
`source_ref`, e um `slug` próprio (ex. `og-ps-112`). Nunca as coloque neste banco público.

## Tipos de questão (`question_type`) e como funcionam as `options`

Toda questão usa a mesma lista `options`; o campo opcional `group` em cada alternativa é o que
diferencia um tipo simples (1 grupo implícito) de um tipo com múltiplas partes (Table Analysis,
Two-Part Analysis, Graphics Interpretation, Multi-Source Reasoning com várias afirmações). O GMAT
não dá crédito parcial: a questão só conta como certa se TODOS os grupos forem respondidos
corretamente.

### `multiple_choice` — Reading Comprehension e Critical Reasoning (Verbal)
5 alternativas, um único grupo implícito (sem `group`). Já usado em
`questions/verbal_reasoning/critical_reasoning_and_rc.yaml` e `questions/quantitative_reasoning/arithmetic_algebra.yaml`
(Quant também é só Problem Solving = múltipla escolha).

### `data_sufficiency` — Data Insights
Mesmo formato de `multiple_choice` (um grupo, 5 alternativas), mas sempre com as 5 alternativas
padrão do formato DS (veja `questions/data_insights/data_sufficiency.yaml` para o texto exato de
cada uma) e o enunciado das duas afirmações no campo `stimulus` como `(1) ...` / `(2) ...`.

### `table_analysis` — Data Insights
Usa `media` para a tabela e várias afirmações Verdadeiro/Falso, uma por `group`:
```yaml
media:
  table:
    columns: ["Cidade", "População", "Renda média"]
    rows:
      - ["Cidade A", "120000", "4200"]
      - ["Cidade B", "95000", "3900"]
  statements:
    - { key: row1, text: "A Cidade A tem renda média maior que a Cidade B." }
    - { key: row2, text: "A Cidade B tem população maior que 100000." }
options:
  - { label: A, text: "Verdadeiro", group: row1, correct: true }
  - { label: B, text: "Falso", group: row1, correct: false }
  - { label: A, text: "Verdadeiro", group: row2, correct: false }
  - { label: B, text: "Falso", group: row2, correct: true }
```

### `two_part_analysis` — Data Insights
Duas colunas de resposta (`part1`/`part2`), cada uma com sua própria lista de opções e um rótulo:
```yaml
media:
  part_labels: { part1: "Valor mínimo", part2: "Valor máximo" }
options:
  - { label: A, text: "10", group: part1, correct: false }
  - { label: B, text: "15", group: part1, correct: true }
  - { label: A, text: "10", group: part2, correct: false }
  - { label: B, text: "15", group: part2, correct: false }
  - { label: C, text: "20", group: part2, correct: true }
```

### `graphics_interpretation` — Data Insights
Igual a `table_analysis`, mas com `media.chart_data` no formato de configuração do
[Chart.js](https://www.chartjs.org/docs/latest/) (campo `type` + `data` + `options`) em vez de
`table`:
```yaml
media:
  chart_data:
    type: bar
    data:
      labels: ["Jan", "Fev", "Mar"]
      datasets: [{ label: "Vendas", data: [10, 15, 12] }]
  statements:
    - { key: dropdown1, text: "O mês com maior valor foi ___." }
```

### `multi_source_reasoning` — Data Insights
Precisa de um `question_sets` (abas compartilhadas por várias questões) declarado no MESMO arquivo
ou em outro já importado antes, referenciado pelo campo `question_set` na questão:
```yaml
question_sets:
  - slug: msr-retail-chain-1
    section: DI
    set_type: multi_source_reasoning
    tabs:
      - { title: "E-mail", content: "Texto da primeira aba..." }
      - { title: "Tabela de vendas", content: "Texto/dados da segunda aba..." }

questions:
  - slug: di-msr-1-q1
    subtopic: di_msr_synthesis
    question_type: multi_source_reasoning
    question_set: msr-retail-chain-1
    set_order: 1
    difficulty: medium
    stem: |
      Com base nas informações apresentadas nas abas, ...
    media:
      statements:
        - { key: stmt1, text: "..." }
        - { key: stmt2, text: "..." }
    options:
      - { label: A, text: "Verdadeiro", group: stmt1, correct: true }
      - { label: B, text: "Falso", group: stmt1, correct: false }
      - { label: A, text: "Verdadeiro", group: stmt2, correct: false }
      - { label: B, text: "Falso", group: stmt2, correct: true }
    explanation: |
      ...
```
Reading Comprehension também pode usar `question_sets` (com `set_type: reading_passage` e
`stimulus_text` em vez de `tabs`) para agrupar várias perguntas sob uma mesma passagem, mesmo
sendo `question_type: multiple_choice`.

## Schema de uma lição (`lessons/*.yaml`)

```yaml
lessons:
  - slug: lesson-qr-quadratic-equations
    subtopic: qr_algebra_quadratic_equations   # 1 lição por subtópico
    title: Equações do 2º grau, fatoração e identidades
    minutes: 25                                # tempo estimado de estudo
    content: |                                 # Markdown: teoria, exemplos resolvidos, armadilhas
      ## 1. Fatoração
      ...
    key_points: |                              # resumo usado nas revisões de teoria espaçadas
      - (x+y)² = x² + 2xy + y²
    flashcards:                                # entram na revisão espaçada quando a lição é concluída
      - { front: "x + y = 6 e xy = 5. x² + y² = ?", back: "26" }
```

A lição é o primeiro passo da trilha; depois vem o teste de fixação (questões N1-N2 do subtópico).
A ordem da trilha fica em `study_plan.yaml`.

## Adicionando um subtópico ou conteúdo novo

Edite `taxonomy_seed.yaml` (adicione o `code`/`name` no lugar certo da árvore) e rode
`python scripts/init_db.py` (ou `seed_taxonomy.py` e depois `import_questions.py`).

## Cobertura mínima (verificada pelos testes)

`tests/test_content_bank.py` valida este banco de exemplo e, se existir, o banco pessoal. Em ambos: formato de cada
tipo, uma alternativa correta por grupo, `answer_check` numérico, equilíbrio de gabaritos e uma lição com pelo menos
3 flashcards por subtópico que tenha questões. No banco pessoal (completo) também exige, por subtópico, pelo menos 3
questões N1-N2, 2 no N3 e 2 no N4-N5, e, para os simulados, pelo menos 21/23/20 questões N3 e N4 em QR/VR/DI.
