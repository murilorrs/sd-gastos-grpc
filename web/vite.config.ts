import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react-swc'
import path from 'path'

// O frontend nunca conhece o endereço dos microsserviços gRPC — só o do
// Gateway. Em produção o nginx da vm-client serve estes arquivos e repassa
// /api para o Gateway, então a base da API é o caminho relativo "/api" e não
// há requisição cross-origin nenhuma. Em desenvolvimento, o proxy abaixo faz
// o mesmo papel do nginx: o navegador continua vendo uma única origem.
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '')
    const gateway = env.GATEWAY_URL || 'http://localhost:8000'

    return {
        plugins: [react()],
        resolve: {
            alias: { '@': path.resolve(__dirname, './src') },
        },
        server: {
            host: true,
            port: Number(env.WEB_PORT || 5173),
            proxy: {
                '/api': {
                    target: gateway,
                    changeOrigin: true,
                    rewrite: (p) => p.replace(/^\/api/, ''),
                },
            },
        },
        preview: { host: true, port: Number(env.WEB_PORT || 5173) },
    }
})
