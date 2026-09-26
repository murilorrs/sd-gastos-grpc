/**
 * Atalhos de período para os filtros da tela.
 *
 * O Gateway filtra por start_date e end_date; estes atalhos só poupam o
 * usuário de digitar as duas datas. A resolução que vale para a linguagem
 * natural continua sendo a do servidor (language/period.py) — aqui é conforto
 * de interface, não regra de negócio.
 */

export interface Range {
    start_date?: string
    end_date?: string
}

const pad = (value: number) => String(value).padStart(2, '0')
const iso = (date: Date) =>
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`

export const QUICK_PERIODS = [
    { id: 'this_month', label: 'Este mês' },
    { id: 'last_month', label: 'Mês passado' },
    { id: 'last_30_days', label: 'Últimos 30 dias' },
    { id: 'this_year', label: 'Este ano' },
    { id: 'all_time', label: 'Tudo' },
] as const

export type QuickPeriod = (typeof QUICK_PERIODS)[number]['id']

export function resolvePeriod(id: QuickPeriod, reference = new Date()): Range {
    const year = reference.getFullYear()
    const month = reference.getMonth()

    switch (id) {
        case 'this_month':
            return { start_date: iso(new Date(year, month, 1)), end_date: iso(new Date(year, month + 1, 0)) }
        case 'last_month':
            return { start_date: iso(new Date(year, month - 1, 1)), end_date: iso(new Date(year, month, 0)) }
        case 'last_30_days': {
            const start = new Date(reference)
            start.setDate(start.getDate() - 29)
            return { start_date: iso(start), end_date: iso(reference) }
        }
        case 'this_year':
            return { start_date: iso(new Date(year, 0, 1)), end_date: iso(new Date(year, 11, 31)) }
        default:
            return {}
    }
}

export const periodLabel = (id: QuickPeriod) =>
    QUICK_PERIODS.find((period) => period.id === id)?.label ?? id
