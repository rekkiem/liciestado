# Gold set — bases anotadas (Obj6)

Rafa aporta **30 bases** (15 TI + 15 Construcción) con PDF + ficha de anotación.

## Formato de cada ficha (JSON)

Un archivo por base: `{codigo}.json` en este directorio.

```json
{
  "codigo": "1234-56-LE26",
  "vertical": "TI",
  "titulo": "Servicio de soporte TI",
  "pdf_path": "data/gold_set/pdfs/1234-56-LE26.pdf",
  "anotacion": {
    "requisitos_obligatorios": ["experiencia 3 años", "certificación ISO"],
    "plazos": {"ofertas_hasta": "2026-11-01", "vigencia_garantia_dias": 60},
    "garantias": ["seriedad 1%", "fiel cumplimiento 5%"],
    "criterios": ["precio 60%", "tecnico 40%"],
    "documentos_exigidos": ["oferta económica", "anexo técnico"]
  },
  "notas": "opcional"
}
```

`vertical` ∈ `TI` | `Construccion`.

## Carga

```bash
python scripts/load_gold_set.py --dir data/gold_set
python scripts/load_gold_set.py --dir data/gold_set --dry-run
```

No se inventan códigos ni anotaciones en el repo: solo el esquema y el cargador.
