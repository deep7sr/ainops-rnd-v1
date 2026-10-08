import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { Shell } from '@/app/shell'
import { ThemeProvider } from '@/app/theme/theme-provider'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AuditPage } from '@/features/audit/audit-page'
import { CasesPage } from '@/features/cases/cases-page'
import { HistoryPage } from '@/features/history/history-page'
import { InventoryPage } from '@/features/inventory/inventory-page'
import { InvestigatePage } from '@/features/investigate/investigate-page'
import { SkillEditorPage } from '@/features/skills/skill-editor'
import { SkillsPage } from '@/features/skills/skills-page'
import { ToolsPage } from '@/features/tools/tools-page'
import { TopologyPage } from '@/features/topology/topology-page'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { path: '/', element: <InvestigatePage /> },
      { path: '/investigations/:id', element: <InvestigatePage /> },
      { path: '/graph', element: <TopologyPage /> },
      { path: '/skills', element: <SkillsPage /> },
      { path: '/skills/new', element: <SkillEditorPage /> },
      { path: '/skills/:name', element: <SkillsPage /> },
      { path: '/skills/:name/edit', element: <SkillEditorPage /> },
      { path: '/tools', element: <ToolsPage /> },
      { path: '/inventory', element: <InventoryPage /> },
      { path: '/inventory/:name', element: <InventoryPage /> },
      { path: '/cases', element: <CasesPage /> },
      { path: '/cases/:id', element: <CasesPage /> },
      { path: '/history', element: <HistoryPage /> },
      { path: '/audit', element: <AuditPage /> },
    ],
  },
])

const root = document.getElementById('root')
if (!root) throw new Error('index.html has no #root element')

createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={200}>
          <RouterProvider router={router} />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
