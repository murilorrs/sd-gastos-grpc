import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react-swc'
import path from 'path'

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
