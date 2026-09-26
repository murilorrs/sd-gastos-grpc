/**
 * Identidade visual, num lugar só.
 *
 * As cores viram custom properties no <html>, e todo o design system em
 * shared/ui/ lê essas variáveis — trocar a marca aqui repinta a aplicação
 * inteira sem tocar em nenhum componente. Verde-azulado sobre azul-noite, que
 * é o que se espera de um aplicativo de dinheiro.
 */

export const brand = {
    appName: 'Grana',
    logo: { primary: 'Gra', accent: 'na' },
    colors: {
        headerBg: '#0F172A',
        primary: '#0D9488',
        primaryHover: '#0F766E',
        accent: '#34D399',
        textDark: '#0F172A',
        accentStrong: '#0D9488',
        accentSoft: '#CCFBF1',
    },
    font: '"IBM Plex Sans", system-ui, -apple-system, sans-serif',
    monoFont: '"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
}

export function applyBrandTheme(): void {
    const root = document.documentElement
    const set = (name: string, value: string) => root.style.setProperty(name, value)

    set('--brand-header-bg', brand.colors.headerBg)
    set('--brand-primary', brand.colors.primary)
    set('--brand-primary-hover', brand.colors.primaryHover)
    set('--brand-accent', brand.colors.accent)
    set('--brand-text-dark', brand.colors.textDark)
    set('--brand-accent-strong', brand.colors.accentStrong)
    set('--brand-accent-soft', brand.colors.accentSoft)
    set('--brand-font', brand.font)
    set('--brand-mono-font', brand.monoFont)

    document.title = brand.appName
}
