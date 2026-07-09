# Risk Radar Output

This note explains how to interpret the risk radar, table columns, and flagged
headline labels in the DAX 40 Audit Risk Radar.

## 1. Risk radar aggregated flags

Each headline goes through a three-model deep-learning pipeline in
`services/nlp.py`:

1. Language detection and translation: German headlines are translated to
   English with MarianMT (`Helsinki-NLP/opus-mt-de-en`).
2. Sentiment: FinBERT (`ProsusAI/finbert`) labels the headline as positive,
   negative, or neutral and returns a confidence score.
3. Zero-shot topic classification: a DeBERTa-v3 MNLI model scores the headline
   against audit-relevant topic labels such as `going concern`, `lawsuit`, and
   `data breach`. Each topic receives an independent score from 0 to 1.

The rule engine in `services/risk.py` then checks those NLP outputs against the
hand-written rules in `domain/isa315_map.yaml`. A rule creates a risk flag when:

- at least one of the rule's trigger topics scores at or above `0.55`, and
- if the rule has a sentiment gate, FinBERT's label and confidence match that
  gate.

Example: `R-GC-01` for Going Concern fires if the headline scores at or above
`0.55` on a topic such as `going concern`, `liquidity crisis`, `covenant
breach`, or `bankruptcy risk`, and the sentiment is negative with a score of at
least `0.70`.

The radar chart aggregates all fired flags across the processed headlines. It
counts flags by ISA 315 category and severity, then plots them as a horizontal
bar chart. A longer bar means more headlines in the selected period triggered
rules in that risk category.

The rules are deliberately stored as YAML data so an auditor can inspect them
without reading Python and understand exactly what can fire.

## 2. Top topic and score

For each headline, the zero-shot classifier assigns a score from 0 to 1 to each
topic label in the catalog. The `Top topic` column shows the topic with the
highest score for that headline. The number in parentheses is that score.

Example: `lawsuit (0.87)` means the model scored the headline strongly as being
about a lawsuit.

The scores are independent per topic, so one headline can score highly on
several topics at once. The table shows only the highest-scoring topic. A top
topic can also be below the `0.55` rule threshold; in that case, it may appear
in the table while `Risk flags` remains empty.

## 3. High, medium, and low labels

The `[HIGH]`, `[MEDIUM]`, and `[LOW]` labels under flagged headlines are the
fixed severities of the rules that fired. Severity comes from
`domain/isa315_map.yaml`; it reflects the audit seriousness of the risk type,
not the model's confidence.

The flagged-headlines list is sorted worst-first, and the same severity colors
drive the radar chart. This mirrors the audit framing: fraud and going-concern
issues are significant risks, while a profit warning may be a lower-severity
subsequent-event signal.

Each expander shows why the flag fired:

- the matched topics and their scores,
- the sentiment label and confidence,
- the relevant ISA and IDW references,
- suggested audit procedures.

The tool supports the auditor's professional judgment. A flag is a transparent
rule firing on a headline, not an actual ISA 315 risk assessment.
