/** Formatação e rótulos em português. O backend fala inglês; a tela, não. */

const CATEGORY_LABELS: Record<string, string> = {
    food: 'Alimentação',
    transport: 'Transporte',
    technology: 'Tecnologia',
    leisure: 'Lazer',
    health: 'Saúde',
    housing: 'Moradia',
    education: 'Educação',
    clothing: 'Vestuário',
    other: 'Outros',
}

const METHOD_LABELS: Record<string, string> = {
    CREDIT: 'Crédito',
    DEBIT: 'Débito',
    credit: 'Crédito',
    debit: 'Débito',
}

export const categoryLabel = (value: string) => CATEGORY_LABELS[value] ?? value
export const methodLabel = (value: string) => METHOD_LABELS[value] ?? value

/** O rótulo certo para a chave de um agrupamento, que muda com o group_by.
 *  Agrupado por cartão, a chave já é o nome do cartão e não se traduz. */
export function totalKeyLabel(groupBy: string, key: string): string {
    if (groupBy === 'category') return categoryLabel(key)
    if (groupBy === 'method') return methodLabel(key)
    return key
}

const money = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })

export const formatMoney = (value: number) => money.format(value || 0)

/** "2026-09-25" -> "25/09/2026". Sem Date: fuso horário estragaria a data. */
export function formatDate(iso: string): string {
    if (!iso) return '—'
    const [year, month, day] = iso.slice(0, 10).split('-')
    return day && month && year ? `${day}/${month}/${year}` : iso
}

/** A data de hoje em YYYY-MM-DD, no fuso local (não em UTC). */
export function today(): string {
    const now = new Date()
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}
