# Ambient RNA Troubleshooting

## Typical signs of ambient RNA contamination

- Unexpected expression of highly abundant genes across many unrelated cells
- Soup-like expression of marker genes in clearly negative clusters
- Inflated background signal in low-UMI cells
- Stress or contamination signatures that do not match known biology

## Common contexts

- Droplet-based single-cell RNA-seq
- Samples with high cell lysis
- Frozen or fragile input material
- Large differences in RNA abundance across cell types

## Triage questions

- Are the suspicious genes also among the most abundant genes in the dataset?
- Do the signals concentrate in low-count cells?
- Is there evidence of poor sample quality or high debris?
- Are doublets and ambient contamination both plausible?

## Practical options

- Tighten QC on low-UMI or low-gene cells
- Compare raw and corrected expression for suspect markers
- Consider SoupX or CellBender when the issue is strong
- Re-check downstream marker interpretation after correction

## Reporting guidance

- State whether ambient RNA is suspected, likely, or unsupported
- List the genes driving suspicion
- Explain how the contamination could affect interpretation
