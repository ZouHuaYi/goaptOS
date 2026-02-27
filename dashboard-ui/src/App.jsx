import { useEffect, useMemo, useState } from 'react'
import { Alert, Card, Col, Layout, Row, Space, Statistic, Table, Tag, Typography } from 'antd'

const { Header, Content } = Layout
const { Title, Text } = Typography

async function safeFetch(path) {
  try {
    const res = await fetch(path)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export default function App() {
  const [dashboard, setDashboard] = useState(null)
  const [strategy, setStrategy] = useState(null)

  useEffect(() => {
    ;(async () => {
      const d = await safeFetch('/data/dashboard.json')
      const s = await safeFetch('/data/strategy_state.json')
      setDashboard(d)
      setStrategy(s)
    })()
  }, [])

  const nodeRows = useMemo(() => {
    const rows = dashboard?.last_result?.node_results || []
    return rows.map((r, idx) => ({ key: idx + 1, ...r }))
  }, [dashboard])

  const topErrors = useMemo(() => {
    const rows = dashboard?.summary?.top_errors || []
    return rows.map((r, i) => ({ key: i + 1, ...r }))
  }, [dashboard])
  const ab = dashboard?.ab_metrics || {}
  const treatment = ab?.treatment || {}
  const control = ab?.control || {}

  const summary = dashboard?.summary || {}
  const assess = dashboard?.last_assessment || {}
  const policy = dashboard?.last_policy || {}
  const proposed = strategy?.proposed?.executor || {}

  return (
    <Layout className="min-h-screen">
      <Header className="!bg-slate-900 flex items-center">
        <Title level={3} className="!text-white !m-0">GTOS God View</Title>
      </Header>
      <Content className="p-6 max-w-7xl mx-auto w-full">
        {!dashboard && (
          <Alert
            type="warning"
            showIcon
            message="No dashboard data found"
            description={'Run "python -m gtos.main --task ..." first, then refresh this page.'}
            className="mb-4"
          />
        )}

        <Row gutter={[16, 16]}>
          <Col xs={24} md={6}><Card><Statistic title="Success Rate" value={((summary.success_rate || 0) * 100).toFixed(2)} suffix="%" /></Card></Col>
          <Col xs={24} md={6}><Card><Statistic title="Avg Latency (ms)" value={summary.avg_latency_ms || 0} /></Card></Col>
          <Col xs={24} md={6}><Card><Statistic title="Avg Fix Rounds" value={summary.avg_fix_rounds || 0} /></Card></Col>
          <Col xs={24} md={6}><Card><Statistic title="Window" value={summary.window || 0} /></Card></Col>
        </Row>

        <Row gutter={[16, 16]} className="mt-1">
          <Col xs={24} lg={12}>
            <Card title="Last Assessment">
              <Space direction="vertical" size={4}>
                <Text>Risk: <Tag color={assess.risk_level === 'high' || assess.risk_level === 'blocked' ? 'red' : assess.risk_level === 'medium' ? 'gold' : 'green'}>{assess.risk_level || 'unknown'}</Tag></Text>
                <Text>Capability: {assess.capability_score ?? '-'}</Text>
                <Text>Task Type: {assess.task_type || '-'}</Text>
                <Text>Dynamic Samples: {assess.dynamic?.samples ?? '-'}</Text>
                <Text>Dynamic Fail Rate: {assess.dynamic?.fail_rate ?? '-'}</Text>
              </Space>
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card title="Current Execution Policy">
              <Space direction="vertical" size={4}>
                <Text>Parallel: {String(policy.parallel ?? false)}</Text>
                <Text>Workers: {policy.max_workers ?? '-'}</Text>
                <Text>Retries: {policy.node_retry_count ?? '-'}</Text>
                <Text>Fail Policy: {policy.fail_policy ?? '-'}</Text>
              </Space>
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]} className="mt-1">
          <Col xs={24} lg={14}>
            <Card title="Node Results">
              <Table
                dataSource={nodeRows}
                pagination={false}
                columns={[
                  { title: 'Node', dataIndex: 'id', key: 'id' },
                  { title: 'Success', dataIndex: 'success', key: 'success', render: (v) => <Tag color={v ? 'green' : 'red'}>{String(v)}</Tag> },
                  { title: 'Skipped', dataIndex: 'skipped', key: 'skipped', render: (v) => String(v) },
                  { title: 'Attempts', dataIndex: 'attempts', key: 'attempts' },
                  { title: 'Latency(ms)', dataIndex: 'latency_ms', key: 'latency_ms' },
                ]}
              />
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card title="Top Errors (Task-level)">
              <Table
                dataSource={topErrors}
                pagination={false}
                columns={[
                  { title: 'Error Type', dataIndex: 'error_type', key: 'error_type' },
                  { title: 'Count', dataIndex: 'count', key: 'count' },
                ]}
              />
            </Card>
            <Card title="Optimizer Proposal" className="mt-4">
              <Space direction="vertical" size={4}>
                <Text>Mode: {strategy?.mode || '-'}</Text>
                <Text>Apply: {String(strategy?.applied ?? false)}</Text>
                <Text>Parallel: {String(proposed.dag_parallel ?? false)}</Text>
                <Text>Workers: {proposed.dag_max_workers ?? '-'}</Text>
                <Text>Retries: {proposed.node_retry_count ?? '-'}</Text>
                <Text>Fail Policy: {proposed.dag_fail_policy ?? '-'}</Text>
              </Space>
            </Card>
            <Card title="Skill A/B Metrics" className="mt-4">
              <Space direction="vertical" size={4}>
                <Text strong>Treatment</Text>
                <Text>Runs: {treatment.runs ?? 0}</Text>
                <Text>Success: {treatment.success_rate ?? '-'}</Text>
                <Text>First-pass: {treatment.first_pass_rate ?? '-'}</Text>
                <Text strong className="mt-2">Control</Text>
                <Text>Runs: {control.runs ?? 0}</Text>
                <Text>Success: {control.success_rate ?? '-'}</Text>
                <Text>First-pass: {control.first_pass_rate ?? '-'}</Text>
              </Space>
            </Card>
          </Col>
        </Row>
      </Content>
    </Layout>
  )
}
