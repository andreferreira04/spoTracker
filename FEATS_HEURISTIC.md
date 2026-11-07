Sim, dá para fazer com uma heurística simples, e os teus dados mostram que vale a pena. Analisei o `music-list.csv`: tem 144.667 plays e 5.126 pares artista/música diferentes.

## Como os feats aparecem

| Formato no título | Músicas |
|---|---|
| `(feat. X)` | 386 |
| `(with X)` | 67 |
| `(Feat. X)`, `(FEAT. X)`, `(feat X)` | 7 |
| `[with X]`, `[feat. X]` | 5 |
| `feat. X`, `ft. X`, `(ft. X)` sem parênteses ou abreviado | 8 |
| No campo do artista: `GP DA ZL feat. MC Jhey` | 1 |

Quase tudo segue o padrão `(feat|ft|with) ...` entre parênteses ou parênteses retos. Uma regex apanha tudo isto:

```
[(\[]?\s*(feat\.?|ft\.?|featuring|with)\s+([^)\]]+)[)\]]?
```

Dentro do feat, os artistas vêm separados por `, ` e `&`, por exemplo `(feat. Sexyy Red & SZA)`.

## O que isto resolveria

Encontrei **53 músicas contadas em duplicado** no mesmo artista, por duas razões:

- **Com e sem feat:**
  - `Dillaz – Querida Já Não Dá` e `Querida Já Não Dá (feat. Veecious V)`
  - `Holly Hood – Some` e `Some (feat. Gson)`
- **Maiúsculas e minúsculas:**
  - `TINA DANCE` e `Tina Dance`
  - `Não Dá Pa Parar` e `Não dá pa parar`

Uma chave normalizada junta estes casos: sem o feat, sem distinguir maiúsculas nem acentos, com espaços limpos. Duas coisas ficam de fora de propósito:

- **Remixes:** ` - Remix`, ` - Live`, ` - Ao Vivo` e afins continuam separados, porque são faixas diferentes.
- **Erros de escrita:** `Mussulo (feat. Doddy)` e `(feat. Dody)` só se juntariam com comparação aproximada. Não recomendo, porque dá falsos positivos.

## Onde a heurística falha, e como a contornar

Separar nomes por `&`, `,` ou `x` é perigoso. `Tyler, The Creator`, `Dimitri Vegas & Like Mike`, `Zion & Lennox` e `A1 x J1` são todos um único artista.

A solução é usar os teus próprios dados como dicionário. Se o texto do feat (ou parte dele) já aparece como artista principal no CSV, fica inteiro. Só se separa o que não é reconhecido. Com 5 mil músicas, este dicionário cobre a maior parte dos casos.

## Proposta

1. **Aplicar só nos relatórios, sem mexer no CSV.** Os dados originais ficam intactos e a heurística pode ser afinada à vontade.
2. **Juntar variantes da mesma música** no top de músicas, mostrando o título mais comum.
3. **Contar os feats no top de artistas**, como um valor à parte ("como principal" / "em feats") ou como filtro. Hoje, a SZA em `Rich Baby Daddy` não conta para nada.
4. **Alinhar o Linux com o Windows.** Pela análise, no Windows o campo do artista traz só o artista principal: quase não há `, ` nesse campo. O código que fiz para Linux junta todos os artistas do MPRIS (`Drake, Sexyy Red, SZA`), o que gravaria os dados de forma diferente consoante o sistema. Devia guardar só o primeiro artista, porque os feats já vêm no título. Ainda não sei o que o AppleScript devolve no macOS para faixas com vários artistas.

Queres que implemente? Se sim, diz-me se o ponto 3 deve ser um valor à parte ou um filtro no relatório.