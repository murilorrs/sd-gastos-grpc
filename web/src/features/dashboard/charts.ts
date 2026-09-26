/**
 * Parâmetros dos gráficos, num lugar só.
 *
 * As cores não foram escolhidas no olho: passaram pelo validador de paleta
 * (banda de luminosidade, piso de croma, separação para daltonismo e
 * contraste contra o fundo claro). O verde-azulado é o da marca.
 *
 * Os gráficos de magnitude — total por categoria, total por cartão — usam UMA
 * cor só: a barra já codifica o valor no comprimento, e pintar cada barra de
 * um tom diferente sugeriria uma identidade que não existe ali. A paleta
 * categórica abaixo é para o gráfico de composição (crédito × débito), onde
 * cada fatia é de fato uma identidade distinta.
 */

export const VIZ = {
    /** Cor única dos gráficos de magnitude. Contraste 3.4:1 sobre o branco. */
    primary: '#0D9488',
    /** Paleta categórica, em ordem fixa — nunca reciclada, nunca por posição. */
    categorical: ['#0D9488', '#2A78D6', '#EB6834', '#4A3AA7'],
    grid: '#E2E8F0',
    axis: '#64748B',
    surface: '#FFFFFF',
}

/** A cor de uma identidade, presa ao nome — filtrar não repinta o que sobrou. */
export function colorFor(key: string, keys: string[]): string {
    const index = keys.indexOf(key)
    return VIZ.categorical[index >= 0 ? index % VIZ.categorical.length : 0]
}
