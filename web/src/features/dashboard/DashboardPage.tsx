import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
    Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { CreditCard, Receipt, Tag, Wallet } from 'lucide-react'
import * as gateway from '@/shared/services/gateway'
import { formatMoney, formatDate, methodLabel, totalKeyLabel } from '@/shared/format'
import { QUICK_PERIODS, QuickPeriod, periodLabel, resolvePeriod } from '@/shared/period'
import { Card } from '@/shared/ui/layout'
import { Badge, EmptyState, StatCard, Table, Tbody, Td, Th, Thead, Tr } from '@/shared/ui/data-display'
import { Spinner } from '@/shared/ui/feedback'
import { VIZ, colorFor } from './charts'
import './DashboardPage.css'

/**
 * O painel: os totais do período escolhido, em números e em gráficos, mais os
 * últimos lançamentos. Trocar o período refaz todas as consultas.
 */
const DashboardPage: React.FC = () => {
    const [period, setPeriod] = useState<QuickPeriod>('this_month')
    const [byCategory, setByCategory] = useState<gateway.Summary | null>(null)
    const [byCard, setByCard] = useState<gateway.Summary | null>(null)
    const [byMethod, setByMethod] = useState<gateway.Summary | null>(null)
    const [recent, setRecent] = useState<gateway.Expense[]>([])
    const [cards, setCards] = useState<gateway.Card[]>([])
    const [loading, setLoading] = useState(true)
    const [failure, setFailure] = useState<string | null>(null)

    const range = useMemo(() => resolvePeriod(period), [period])

    const load = useCallback(async () => {
        setLoading(true)
        setFailure(null)
        try {
            const [category, card, method, expenses, registered] = await Promise.all([
                gateway.summary('category', range),
                gateway.summary('card', range),
                gateway.summary('method', range),
                gateway.listExpenses(range),
                gateway.listCards(),
            ])
            setByCategory(category)
            setByCard(card)
            setByMethod(method)
            setRecent(expenses.slice(0, 6))
            setCards(registered)
        } catch (error) {
            setFailure(error instanceof Error ? error.message : 'Falha ao carregar o painel.')
        } finally {
            setLoading(false)
        }
    }, [range])

    useEffect(() => { void load() }, [load])

    const total = byCategory?.grand_total ?? 0
    const count = byCategory?.totals.reduce((sum, item) => sum + item.count, 0) ?? 0
    const biggest = byCategory?.totals[0]

    const categoryData = (byCategory?.totals ?? []).map((item) => ({
        name: totalKeyLabel('category', item.key),
        total: item.total,
        count: item.count,
    }))
    const cardData = (byCard?.totals ?? []).map((item) => ({
        name: item.key, total: item.total, count: item.count,
    }))
    const methodKeys = (byMethod?.totals ?? []).map((item) => item.key)
    const methodData = (byMethod?.totals ?? []).map((item) => ({
        name: methodLabel(item.key),
        key: item.key,
        total: item.total,
        count: item.count,
    }))

    return (
        <>
            <div className="page-head">
                <div>
                    <h1>Painel</h1>
                </div>
                <div className="period-chips" role="group" aria-label="Período">
                    {QUICK_PERIODS.map((option) => (
                        <button
                            key={option.id}
                            type="button"
                            className={`period-chip${period === option.id ? ' is-active' : ''}`}
                            onClick={() => setPeriod(option.id)}
                        >
                            {option.label}
                        </button>
                    ))}
                </div>
            </div>

            {failure && <Card className="dashboard-failure">{failure}</Card>}

            {loading ? (
                <Card className="dashboard-loading"><Spinner size="lg" /></Card>
            ) : (
                <>
                    <div className="grid-stats">
                        <StatCard
                            label="Total no período" value={formatMoney(total)}
                            icon={<Wallet size={18} />} variant="primary"
                            description={periodLabel(period)}
                        />
                        <StatCard
                            label="Gastos registrados" value={count}
                            icon={<Receipt size={18} />} variant="info"
                            description={count === 1 ? '1 lançamento' : `${count} lançamentos`}
                        />
                        <StatCard
                            label="Maior categoria"
                            value={biggest ? totalKeyLabel('category', biggest.key) : '—'}
                            icon={<Tag size={18} />} variant="warning"
                            description={biggest ? formatMoney(biggest.total) : 'sem gastos no período'}
                        />
                        <StatCard
                            label="Cartões cadastrados" value={cards.length}
                            icon={<CreditCard size={18} />} variant="success"
                            description={cards.map((card) => card.name).join(', ') || 'nenhum ainda'}
                        />
                    </div>

                    <div className="grid-halves">
                        <Card>
                            <div className="card-head">
                                <h2>Total por categoria</h2>
                            </div>
                            <MagnitudeChart data={categoryData} empty="Nenhum gasto no período." />
                        </Card>

                        <Card>
                            <div className="card-head">
                                <h2>Crédito × Débito</h2>
                            </div>
                            {methodData.length === 0 ? (
                                <p className="chart-empty">Nenhum gasto no período.</p>
                            ) : (
                                <div className="chart-split">
                                    <ResponsiveContainer width="100%" height={200}>
                                        <PieChart>
                                            <Pie
                                                data={methodData} dataKey="total" nameKey="name"
                                                innerRadius={50} outerRadius={78} paddingAngle={1}
                                                stroke={VIZ.surface} strokeWidth={2}
                                            >
                                                {methodData.map((slice) => (
                                                    <Cell key={slice.key} fill={colorFor(slice.key, methodKeys)} />
                                                ))}
                                            </Pie>
                                            <Tooltip content={<MoneyTooltip />} />
                                        </PieChart>
                                    </ResponsiveContainer>
                                    {/* Legenda com o valor ao lado: a identidade nunca
                                        depende só da cor. */}
                                    <ul className="chart-legend">
                                        {methodData.map((slice) => (
                                            <li key={slice.key}>
                                                <span
                                                    className="chart-swatch"
                                                    style={{ background: colorFor(slice.key, methodKeys) }}
                                                />
                                                <span className="chart-legend-name">{slice.name}</span>
                                                <span className="chart-legend-value amount">
                                                    {formatMoney(slice.total)}
                                                </span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </Card>
                    </div>

                    <div className="grid-halves">
                        <Card>
                            <div className="card-head">
                                <h2>Total por cartão</h2>
                            </div>
                            <MagnitudeChart data={cardData} empty="Nenhum gasto no período." />
                        </Card>

                        <Card>
                            <div className="card-head">
                                <h2>Últimos gastos</h2>
                                <Link className="card-head-link" to="/gastos">ver todos</Link>
                            </div>
                            {recent.length === 0 ? (
                                <EmptyState
                                    icon={<Receipt size={28} />}
                                    title="Nenhum gasto no período"
                                    description="Escolha outro período ou registre o primeiro lançamento."
                                />
                            ) : (
                                <Table>
                                    <Thead>
                                        <Tr>
                                            <Th>Produto</Th>
                                            <Th>Cartão</Th>
                                            <Th>Data</Th>
                                            <Th align="right">Valor</Th>
                                        </Tr>
                                    </Thead>
                                    <Tbody>
                                        {recent.map((expense) => (
                                            <Tr key={expense.id}>
                                                <Td>
                                                    {/* Produto e categoria na mesma linha: a etiqueta
                                                        quebrando embaixo dobrava a altura da linha. */}
                                                    <div className="recent-product">
                                                        <span>{expense.product}</span>
                                                        <Badge variant="gray">
                                                            {totalKeyLabel('category', expense.category)}
                                                        </Badge>
                                                    </div>
                                                </Td>
                                                <Td>
                                                    {expense.card}
                                                    <span className="muted"> · {methodLabel(expense.method)}</span>
                                                </Td>
                                                <Td>{formatDate(expense.date)}</Td>
                                                <Td align="right"><span className="amount">{formatMoney(expense.amount)}</span></Td>
                                            </Tr>
                                        ))}
                                    </Tbody>
                                </Table>
                            )}
                        </Card>
                    </div>
                </>
            )}
        </>
    )
}

/** Barras horizontais de uma série só: o comprimento é o dado, a cor não. */
const MagnitudeChart: React.FC<{
    data: { name: string; total: number; count: number }[]
    empty: string
}> = ({ data, empty }) => {
    if (data.length === 0) return <p className="chart-empty">{empty}</p>

    return (
        <ResponsiveContainer width="100%" height={Math.max(160, data.length * 42)}>
            <BarChart data={data} layout="vertical" margin={{ top: 4, right: 56, bottom: 4, left: 4 }}>
                <XAxis type="number" hide />
                <YAxis
                    type="category" dataKey="name" width={96} axisLine={false} tickLine={false}
                    tick={{ fill: VIZ.axis, fontSize: 12 }}
                />
                <Tooltip content={<MoneyTooltip />} cursor={{ fill: 'rgba(15,23,42,0.04)' }} />
                {/* Ponta com 2px: o suficiente para a barra terminar num corte
                    limpo, sem virar cápsula. */}
                <Bar
                    dataKey="total" fill={VIZ.primary} radius={[0, 2, 2, 0]}
                    barSize={14} label={<ValueLabel />}
                />
            </BarChart>
        </ResponsiveContainer>
    )
}

/** Rótulo direto na ponta da barra — dispensa eixo de valores. */
const ValueLabel = (props: any) => {
    const { x = 0, y = 0, width = 0, height = 0, value } = props
    return (
        <text
            x={x + width + 8} y={y + height / 2} dy={4}
            fill={VIZ.axis} fontSize={11.5} fontVariant="tabular-nums"
        >
            {formatMoney(Number(value))}
        </text>
    )
}

const MoneyTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null
    const point = payload[0].payload as { name: string; total: number; count: number }
    return (
        <div className="chart-tooltip">
            <strong>{point.name}</strong>
            <span>{formatMoney(point.total)}</span>
            <span className="muted">
                {point.count} {point.count === 1 ? 'gasto' : 'gastos'}
            </span>
        </div>
    )
}

export default DashboardPage
