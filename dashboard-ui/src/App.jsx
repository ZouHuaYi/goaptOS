import {
  BarChartOutlined,
  ClearOutlined,
  DeleteOutlined,
  LeftOutlined,
  MenuOutlined,
  MessageOutlined,
  PlusOutlined,
  PushpinFilled,
  PushpinOutlined,
  ReloadOutlined,
  RightOutlined,
  RobotOutlined,
  SendOutlined,
  StopOutlined,
  UserOutlined
} from '@ant-design/icons'
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Card,
  Select,
  Col,
  ConfigProvider,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Input,
  Layout,
  List,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'

const { Header, Content, Sider } = Layout
const { Title, Text, Paragraph } = Typography
const { TextArea, Search } = Input

const STORAGE_KEY = 'gtos_chat_sessions_v2'

function newSession() {
  const id = `s_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`
  return {
    id,
    title: '新会话',
    pinned: false,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    lastPayload: null,
    messages: [{ role: 'assistant', content: '你好，我是 GTOS 助手。请直接告诉我任务目标。', ts: Date.now() }],
  }
}

async function safeFetch(path) {
  try {
    const res = await fetch(path)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

function RiskTag({ risk }) {
  const color = risk === 'high' || risk === 'blocked' ? 'red' : risk === 'medium' ? 'gold' : 'green'
  return <Tag color={color}>{risk || 'unknown'}</Tag>
}

function sortSessions(items) {
  return [...items].sort((a, b) => {
    if (Boolean(a.pinned) !== Boolean(b.pinned)) return a.pinned ? -1 : 1
    return b.updatedAt - a.updatedAt
  })
}

function renderMessageContent(content) {
  const txt = String(content || '')
  if (!txt.includes('```')) return <div style={{ whiteSpace: 'pre-wrap' }}>{txt}</div>
  const parts = txt.split('```')
  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      {parts.map((p, idx) => {
        const chunk = p.trim()
        if (!chunk) return null
        const isCode = idx % 2 === 1
        if (isCode) {
          const clean = chunk.replace(/^\w+\n/, '')
          return (
            <pre key={idx} className="chat-code-block">
              {clean}
            </pre>
          )
        }
        return <div key={idx} style={{ whiteSpace: 'pre-wrap' }}>{chunk}</div>
      })}
    </Space>
  )
}

function Sparkline({ points = [], color = '#1677ff' }) {
  if (!points.length) return <Text type="secondary">暂无曲线数据</Text>
  const width = 220
  const height = 64
  const xs = points.map((_, i) => i)
  const ys = points.map((p) => Number(p?.average_reward || 0))
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const xScale = (x) => (xs.length <= 1 ? 0 : (x / (xs.length - 1)) * (width - 8) + 4)
  const yScale = (y) => {
    if (maxY === minY) return height / 2
    return height - (((y - minY) / (maxY - minY)) * (height - 12) + 6)
  }
  const d = ys.map((y, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i).toFixed(2)} ${yScale(y).toFixed(2)}`).join(' ')
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <path d={d} fill="none" stroke={color} strokeWidth="2" />
    </svg>
  )
}

export default function App() {
  const [dashboard, setDashboard] = useState(null)
  const [strategy, setStrategy] = useState(null)
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [apiUp, setApiUp] = useState(true)
  const [sessions, setSessions] = useState([newSession()])
  const [activeSessionId, setActiveSessionId] = useState('')
  const [sessionQuery, setSessionQuery] = useState('')
  const [isMobile, setIsMobile] = useState(false)
  const [banditBucket, setBanditBucket] = useState('')

  const abortRef = useRef(null)
  const messageBoxRef = useRef(null)

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) || sessions[0] || null,
    [sessions, activeSessionId]
  )

  const orderedSessions = useMemo(() => sortSessions(sessions), [sessions])
  const filteredSessions = useMemo(() => {
    const q = sessionQuery.trim().toLowerCase()
    if (!q) return orderedSessions
    return orderedSessions.filter((s) => (s.title || '').toLowerCase().includes(q))
  }, [orderedSessions, sessionQuery])

  const summary = dashboard?.summary || {}
  const assess = dashboard?.last_assessment || {}
  const policy = dashboard?.last_policy || {}
  const skillLifecycle = dashboard?.skill_lifecycle || {}
  const skillDrafts = dashboard?.skill_drafts || {}
  const adaptive = dashboard?.adaptive_engine || {}
  const bandit = dashboard?.bandit || {}
  const proposed = strategy?.proposed?.executor || {}
  const ab = dashboard?.ab_metrics || {}
  const treatment = ab?.treatment || {}
  const control = ab?.control || {}

  const nodeRows = useMemo(() => {
    const rows = dashboard?.last_result?.node_results || []
    return rows.map((r, idx) => ({ key: idx + 1, ...r }))
  }, [dashboard])

  const topErrors = useMemo(() => {
    const rows = dashboard?.summary?.top_errors || []
    return rows.map((r, i) => ({ key: i + 1, ...r }))
  }, [dashboard])

  const skillBucketRows = useMemo(() => {
    const b = skillLifecycle?.score_buckets || {}
    return Object.keys(b).map((k, i) => ({ key: i + 1, bucket: k, count: b[k] || 0 }))
  }, [skillLifecycle])

  const recentDraftRows = useMemo(() => {
    const rows = skillDrafts?.recent || []
    return rows.map((r, i) => ({ key: i + 1, ...r }))
  }, [skillDrafts])

  const capabilityRows = useMemo(() => {
    const rows = adaptive?.top || []
    return rows.map((r, i) => ({ key: i + 1, ...r }))
  }, [adaptive])

  const banditBucketRows = useMemo(() => {
    const buckets = bandit?.buckets || {}
    return Object.keys(buckets).map((k, i) => ({
      key: i + 1,
      bucket: k,
      total_pulls_ucb: buckets[k]?.total_pulls_ucb || 0,
      total_pulls_thompson: buckets[k]?.total_pulls_thompson || 0,
    }))
  }, [bandit])

  const banditBucketOptions = useMemo(() => Object.keys(bandit?.buckets || {}).map((k) => ({ label: k, value: k })), [bandit])

  useEffect(() => {
    if (!banditBucket && banditBucketOptions.length > 0) {
      setBanditBucket(banditBucketOptions[0].value)
    }
  }, [banditBucket, banditBucketOptions])

  const selectedBandit = useMemo(() => {
    const buckets = bandit?.buckets || {}
    return buckets[banditBucket] || null
  }, [bandit, banditBucket])

  const banditCurveRows = useMemo(() => {
    const points = (bandit?.curves || {})[banditBucket] || []
    const grouped = {}
    points.forEach((p) => {
      const arm = p.arm || 'unknown'
      if (!grouped[arm]) grouped[arm] = []
      grouped[arm].push(p)
    })
    return Object.keys(grouped).map((arm, i) => ({ key: i + 1, arm, points: grouped[arm].slice(-40) }))
  }, [bandit, banditBucket])

  function updateSessionById(sessionId, updater) {
    setSessions((prev) => sortSessions(prev.map((s) => (s.id === sessionId ? updater(s) : s))))
  }

  async function refreshAll() {
    const [d, s] = await Promise.all([
      safeFetch('/data/dashboard.json'),
      safeFetch('/data/strategy_state.json'),
    ])
    setDashboard(d)
    setStrategy(s)
  }

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 992)
    onResize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
    } catch {
      // ignore
    }
  }, [sessions])

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed) && parsed.length > 0) {
          const normalized = parsed.map((s) => ({ ...s, pinned: Boolean(s.pinned) }))
          const sorted = sortSessions(normalized)
          setSessions(sorted)
          setActiveSessionId(sorted[0].id)
        }
      } else {
        const s = newSession()
        setSessions([s])
        setActiveSessionId(s.id)
      }
    } catch {
      const s = newSession()
      setSessions([s])
      setActiveSessionId(s.id)
    }
    refreshAll()
    ;(async () => {
      const h = await safeFetch('/api/health')
      setApiUp(Boolean(h?.ok))
    })()
  }, [])

  useEffect(() => {
    const el = messageBoxRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [activeSession?.messages, chatLoading])

  function createSessionAndSelect() {
    const s = newSession()
    setSessions((prev) => sortSessions([s, ...prev]))
    setActiveSessionId(s.id)
    setSessionDrawerOpen(false)
  }

  function removeSession(id) {
    setSessions((prev) => {
      const left = prev.filter((s) => s.id !== id)
      if (left.length === 0) {
        const s = newSession()
        setActiveSessionId(s.id)
        return [s]
      }
      const sorted = sortSessions(left)
      if (activeSessionId === id) setActiveSessionId(sorted[0].id)
      return sorted
    })
  }

  function togglePin(id) {
    setSessions((prev) => sortSessions(prev.map((s) => (s.id === id ? { ...s, pinned: !s.pinned, updatedAt: Date.now() } : s))))
  }

  function clearActiveChat() {
    if (!activeSession) return
    updateSessionById(activeSession.id, (s) => ({
      ...s,
      title: '新会话',
      lastPayload: null,
      updatedAt: Date.now(),
      messages: [{ role: 'assistant', content: '对话已清空。请输入新的任务目标。', ts: Date.now() }],
    }))
  }

  async function sendChat(textInput) {
    if (!activeSession) return
    const sessionId = activeSession.id
    const text = (textInput ?? chatInput).trim()
    if (!text || chatLoading) return
    setChatInput('')

    const reqId = `req_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`

    updateSessionById(sessionId, (s) => {
      const title = s.title === '新会话' ? text.replace(/\s+/g, ' ').slice(0, 20) : s.title
      return {
        ...s,
        title,
        updatedAt: Date.now(),
        messages: [
          ...s.messages,
          { role: 'user', content: text, ts: Date.now() },
          { id: reqId, role: 'assistant', content: '正在思考中...', pending: true, ts: Date.now() },
        ],
      }
    })

    setChatLoading(true)
    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
        signal: ctrl.signal,
      })
      const data = await res.json()
      if (!res.ok || !data?.ok) {
        updateSessionById(sessionId, (s) => ({
          ...s,
          updatedAt: Date.now(),
          messages: s.messages.map((m) =>
            m.id === reqId ? { ...m, pending: false, content: `请求失败：${data?.error || res.status}` } : m
          ),
        }))
        message.error('请求失败，请检查后端服务')
      } else {
        updateSessionById(sessionId, (s) => ({
          ...s,
          updatedAt: Date.now(),
          lastPayload: data,
          messages: s.messages.map((m) =>
            m.id === reqId ? { ...m, pending: false, content: data.reply || '任务执行完成。' } : m
          ),
        }))
        await refreshAll()
      }
    } catch (e) {
      const aborted = ctrl.signal.aborted
      updateSessionById(sessionId, (s) => ({
        ...s,
        updatedAt: Date.now(),
        messages: s.messages.map((m) =>
          m.id === reqId ? { ...m, pending: false, content: aborted ? '已停止当前请求。' : `网络错误：${String(e)}` } : m
        ),
      }))
      if (!aborted) message.error('网络错误，无法连接到 /api/chat')
    } finally {
      abortRef.current = null
      setChatLoading(false)
    }
  }

  function stopCurrentRequest() {
    if (abortRef.current) abortRef.current.abort()
  }

  const showRightPanel = !isMobile && !rightCollapsed

  const sessionListNode = (
    <Space direction="vertical" style={{ width: '100%' }} size={10}>
      <Button type="primary" icon={<PlusOutlined />} block onClick={createSessionAndSelect}>新建会话</Button>
      <Search placeholder="搜索会话" allowClear value={sessionQuery} onChange={(e) => setSessionQuery(e.target.value)} />
      <List
        size="small"
        dataSource={filteredSessions}
        locale={{ emptyText: '暂无会话' }}
        renderItem={(item) => (
          <List.Item
            className="session-item"
            style={{
              border: item.id === activeSession?.id ? '1px solid #1677ff' : '1px solid #e5e7eb',
            }}
            onClick={() => {
              setActiveSessionId(item.id)
              setSessionDrawerOpen(false)
            }}
            actions={[
              <Button
                key="pin"
                size="small"
                type="text"
                icon={item.pinned ? <PushpinFilled /> : <PushpinOutlined />}
                onClick={(e) => {
                  e.stopPropagation()
                  togglePin(item.id)
                }}
              />,
              <Button
                key="del"
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={(e) => {
                  e.stopPropagation()
                  removeSession(item.id)
                }}
              />,
            ]}
          >
            <List.Item.Meta
              avatar={<Avatar icon={<MessageOutlined />} />}
              title={<Text ellipsis style={{ maxWidth: 140 }}>{item.title || '新会话'}</Text>}
              description={<Text type="secondary">{new Date(item.updatedAt).toLocaleString()}</Text>}
            />
          </List.Item>
        )}
      />
    </Space>
  )

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 12,
          colorBgContainer: '#ffffff',
        },
      }}
    >
      <Layout className="app-shell">
        <Header className="top-header">
          <Space>
            {isMobile ? <Button icon={<MenuOutlined />} onClick={() => setSessionDrawerOpen(true)} /> : null}
            <BarChartOutlined style={{ color: '#fff', fontSize: 18 }} />
            <Title level={4} style={{ color: '#fff', margin: 0 }}>GTOS 控制台</Title>
            <Badge status={apiUp ? 'success' : 'error'} text={<span style={{ color: '#dbeafe' }}>{apiUp ? 'API 在线' : 'API 离线'}</span>} />
          </Space>
          <Button icon={<ReloadOutlined />} onClick={refreshAll}>刷新面板</Button>
        </Header>

        <Layout className="main-layout">
          {!isMobile ? (
            <Sider width={300} className="left-sider">
              <div className="session-list-wrap">
                {sessionListNode}
              </div>
            </Sider>
          ) : null}

          <Content className="main-content">
            {!dashboard ? (
              <Alert
                type="warning"
                showIcon
                message="未发现监控数据"
                description='请先运行 "python -m gtos.main --task ..." 或通过对话发送一次任务。'
                style={{ marginBottom: 12 }}
              />
            ) : null}

            <Tabs
              className="main-tabs"
              style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
              tabBarStyle={{ marginBottom: 12, flexShrink: 0 }}
              defaultActiveKey="chat"
              items={[
                {
                  key: 'chat',
                  label: <span><MessageOutlined /> 对话交互</span>,
                  children: (
                    <Row gutter={[16, 16]} className="chat-tab-row" style={{ height: '100%', margin: 0 }}>
                      <Col xs={24} lg={showRightPanel ? 16 : 24} style={{ height: '100%', minHeight: 0 }}>
                        <Card
                          className="chat-card"
                          style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' }}
                          title={activeSession?.title || '任务对话'}
                          extra={
                            <Space>
                              {!isMobile ? (
                                <Button size="small" icon={rightCollapsed ? <LeftOutlined /> : <RightOutlined />} onClick={() => setRightCollapsed((v) => !v)}>
                                  {rightCollapsed ? '展开侧栏' : '收起侧栏'}
                                </Button>
                              ) : null}
                              <Button size="small" icon={<ClearOutlined />} onClick={clearActiveChat}>清空</Button>
                              <Button size="small" onClick={() => setDrawerOpen(true)} disabled={!activeSession?.lastPayload}>查看详情</Button>
                            </Space>
                          }
                          bodyStyle={{ padding: 12, flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}
                        >
                          <div ref={messageBoxRef} className="chat-scroll-region">
                            {!activeSession?.messages?.length ? (
                              <Empty description="暂无消息" />
                            ) : (
                              <List
                                dataSource={activeSession.messages}
                                renderItem={(item) => (
                                  <List.Item style={{ border: 'none', padding: '8px 0' }}>
                                    <div style={{ width: '100%', display: 'flex', justifyContent: item.role === 'user' ? 'flex-end' : 'flex-start' }}>
                                      <Space align="start">
                                        {item.role !== 'user' ? <Avatar icon={<RobotOutlined />} /> : null}
                                        <div className={item.role === 'user' ? 'msg-bubble user' : 'msg-bubble assistant'}>
                                          <div>{renderMessageContent(item.content)}</div>
                                          {item.pending ? <div style={{ marginTop: 8 }}><Spin size="small" /> <Text type="secondary">正在生成中...</Text></div> : null}
                                        </div>
                                        {item.role === 'user' ? <Avatar icon={<UserOutlined />} style={{ background: '#1677ff' }} /> : null}
                                      </Space>
                                    </div>
                                  </List.Item>
                                )}
                              />
                            )}
                          </div>

                          <div className="chat-composer-fixed">
                            <TextArea
                              rows={4}
                              value={chatInput}
                              onChange={(e) => setChatInput(e.target.value)}
                              onPressEnter={(e) => {
                                if (!e.shiftKey) {
                                  e.preventDefault()
                                  sendChat()
                                }
                              }}
                              placeholder="请输入任务。回车发送，Shift+回车换行。"
                            />

                            <div className="composer-actions">
                              <Text type="secondary">输入区固定底部，消息区独立滚动。</Text>
                              <Space>
                                {chatLoading ? <Button danger icon={<StopOutlined />} onClick={stopCurrentRequest}>停止</Button> : null}
                                <Button type="primary" icon={<SendOutlined />} onClick={() => sendChat()} loading={chatLoading}>发送</Button>
                              </Space>
                            </div>
                          </div>
                        </Card>
                      </Col>

                      {showRightPanel ? (
                      <Col xs={24} lg={8} className="chat-right-panel" style={{ height: '100%', paddingRight: 2 }}>
                        <Space direction="vertical" size={16} style={{ width: '100%' }}>
                          <Card title="运行总览">
                            <Row gutter={12}>
                              <Col span={12}><Statistic title="成功率" value={((summary.success_rate || 0) * 100).toFixed(2)} suffix="%" /></Col>
                              <Col span={12}><Statistic title="窗口" value={summary.window || 0} /></Col>
                              <Col span={12}><Statistic title="平均延迟" value={summary.avg_latency_ms || 0} suffix="ms" /></Col>
                              <Col span={12}><Statistic title="平均修复轮次" value={summary.avg_fix_rounds || 0} /></Col>
                            </Row>
                          </Card>

                          <Card title="认知与策略">
                            <Descriptions size="small" column={1} labelStyle={{ width: 108 }}>
                              <Descriptions.Item label="风险等级"><RiskTag risk={assess.risk_level} /></Descriptions.Item>
                              <Descriptions.Item label="能力分">{assess.capability_score ?? '-'}</Descriptions.Item>
                              <Descriptions.Item label="任务类型">{assess.task_type ?? '-'}</Descriptions.Item>
                              <Descriptions.Item label="并行">{String(policy.parallel ?? false)}</Descriptions.Item>
                              <Descriptions.Item label="并发数">{policy.max_workers ?? '-'}</Descriptions.Item>
                              <Descriptions.Item label="失败策略">{policy.fail_policy ?? '-'}</Descriptions.Item>
                            </Descriptions>
                          </Card>

                          <Card title="技能 A/B">
                            <Row gutter={12}>
                              <Col span={12}>
                                <Text strong>实验组</Text>
                                <Paragraph style={{ marginBottom: 8 }}>样本: {treatment.runs ?? 0}</Paragraph>
                                <Paragraph style={{ marginBottom: 8 }}>成功率: {treatment.success_rate ?? '-'}</Paragraph>
                                <Paragraph style={{ marginBottom: 0 }}>首轮成功: {treatment.first_pass_rate ?? '-'}</Paragraph>
                              </Col>
                              <Col span={12}>
                                <Text strong>对照组</Text>
                                <Paragraph style={{ marginBottom: 8 }}>样本: {control.runs ?? 0}</Paragraph>
                                <Paragraph style={{ marginBottom: 8 }}>成功率: {control.success_rate ?? '-'}</Paragraph>
                                <Paragraph style={{ marginBottom: 0 }}>首轮成功: {control.first_pass_rate ?? '-'}</Paragraph>
                              </Col>
                            </Row>
                          </Card>

                          <Card title="技能生命周期">
                            <Row gutter={12}>
                              <Col span={12}><Statistic title="总技能" value={skillLifecycle.total || 0} /></Col>
                              <Col span={12}><Statistic title="平均分" value={skillLifecycle.avg_score || 0} precision={3} /></Col>
                              <Col span={12}><Statistic title="活跃" value={skillLifecycle.active || 0} /></Col>
                              <Col span={12}><Statistic title="过期" value={skillLifecycle.expired || 0} /></Col>
                            </Row>
                            <Divider style={{ margin: '12px 0' }} />
                            <Row gutter={12}>
                              <Col span={12}><Statistic title="草案总数" value={skillDrafts.total || 0} /></Col>
                              <Col span={12}><Statistic title="待采纳草案" value={skillDrafts.proposed || 0} /></Col>
                              <Col span={12}><Statistic title="采纳率" value={((skillDrafts.acceptance_rate || 0) * 100).toFixed(2)} suffix="%" /></Col>
                              <Col span={12}><Statistic title="平均分数提升" value={skillDrafts.avg_score_uplift || 0} precision={4} /></Col>
                              <Col span={12}><Statistic title="能力画像数" value={adaptive.total || 0} /></Col>
                              <Col span={12}><Statistic title="Bandit 分桶数" value={bandit.bucket_count || 0} /></Col>
                            </Row>
                          </Card>
                        </Space>
                      </Col>
                      ) : null}
                    </Row>
                  ),
                },
                {
                  key: 'dashboard',
                  label: <span><BarChartOutlined /> 监控面板</span>,
                  children: (
                    <div className="dashboard-panel-wrap" style={{ height: '100%', paddingRight: 2 }}>
                      <Row gutter={[16, 16]}>
                        <Col xs={24} lg={14}>
                          <Card title="节点执行结果">
                            <Table
                              dataSource={nodeRows}
                              rowKey="key"
                              pagination={{ pageSize: 8, showSizeChanger: true, pageSizeOptions: ['8', '16', '24'] }}
                              columns={[
                                { title: '节点', dataIndex: 'id' },
                                {
                                  title: '成功',
                                  dataIndex: 'success',
                                  filters: [{ text: '成功', value: 'true' }, { text: '失败', value: 'false' }],
                                  onFilter: (v, r) => String(r.success) === String(v),
                                  render: (v) => <Tag color={v ? 'green' : 'red'}>{String(v)}</Tag>,
                                },
                                {
                                  title: '跳过',
                                  dataIndex: 'skipped',
                                  filters: [{ text: '是', value: 'true' }, { text: '否', value: 'false' }],
                                  onFilter: (v, r) => String(Boolean(r.skipped)) === String(v),
                                  render: (v) => String(Boolean(v)),
                                },
                                { title: '尝试次数', dataIndex: 'attempts', sorter: (a, b) => (a.attempts || 0) - (b.attempts || 0) },
                                { title: '延迟(ms)', dataIndex: 'latency_ms', sorter: (a, b) => (a.latency_ms || 0) - (b.latency_ms || 0) },
                              ]}
                            />
                          </Card>
                        </Col>
                        <Col xs={24} lg={10}>
                          <Card title="错误类型（任务级）">
                            <Table
                              dataSource={topErrors}
                              rowKey="key"
                              pagination={{ pageSize: 6, showSizeChanger: false }}
                              columns={[
                                { title: '错误类型', dataIndex: 'error_type' },
                                { title: '次数', dataIndex: 'count', sorter: (a, b) => (a.count || 0) - (b.count || 0) },
                              ]}
                            />
                          </Card>
                          <Card title="优化器建议" style={{ marginTop: 16 }}>
                            <Descriptions size="small" column={1} labelStyle={{ width: 120 }}>
                              <Descriptions.Item label="模式">{strategy?.mode || '-'}</Descriptions.Item>
                              <Descriptions.Item label="自动应用">{String(strategy?.applied ?? false)}</Descriptions.Item>
                              <Descriptions.Item label="建议并行">{String(proposed.dag_parallel ?? false)}</Descriptions.Item>
                              <Descriptions.Item label="建议并发数">{proposed.dag_max_workers ?? '-'}</Descriptions.Item>
                              <Descriptions.Item label="建议重试数">{proposed.node_retry_count ?? '-'}</Descriptions.Item>
                              <Descriptions.Item label="建议失败策略">{proposed.dag_fail_policy ?? '-'}</Descriptions.Item>
                            </Descriptions>
                          </Card>

                          <Card title="技能分数分布" style={{ marginTop: 16 }}>
                            <Table
                              dataSource={skillBucketRows}
                              rowKey="key"
                              pagination={false}
                              columns={[
                                { title: '分数区间', dataIndex: 'bucket' },
                                { title: '技能数', dataIndex: 'count', sorter: (a, b) => (a.count || 0) - (b.count || 0) },
                              ]}
                            />
                          </Card>

                          <Card title="最近优化草案" style={{ marginTop: 16 }}>
                            <Table
                              dataSource={recentDraftRows}
                              rowKey="key"
                              pagination={{ pageSize: 5, showSizeChanger: false }}
                              columns={[
                                { title: '草案', dataIndex: 'draft_id', render: (v) => <Text code>{String(v || '').slice(-8)}</Text> },
                                { title: '来源版本', dataIndex: 'from_version' },
                                { title: '目标版本', dataIndex: 'target_version' },
                                { title: '分数提升', dataIndex: ['acceptance', 'score_uplift'], render: (v) => (v === undefined ? '-' : Number(v).toFixed(4)) },
                                { title: '状态', dataIndex: 'status', render: (v) => <Tag color={v === 'accepted' ? 'green' : v === 'rejected' ? 'red' : 'gold'}>{v || 'proposed'}</Tag> },
                              ]}
                            />
                          </Card>

                          <Card title="能力优先级画像" style={{ marginTop: 16 }}>
                            <Table
                              dataSource={capabilityRows}
                              rowKey="key"
                              pagination={{ pageSize: 5, showSizeChanger: false }}
                              columns={[
                                { title: '能力', dataIndex: 'name' },
                                { title: '成功率', dataIndex: 'success_rate', render: (v) => `${(Number(v || 0) * 100).toFixed(1)}%` },
                                { title: '平均耗时(ms)', dataIndex: 'avg_time_ms', render: (v) => Number(v || 0).toFixed(0) },
                                { title: '使用次数', dataIndex: 'usage_count' },
                              ]}
                            />
                          </Card>

                          <Card title="Bandit 分桶概览" style={{ marginTop: 16 }}>
                            <Table
                              dataSource={banditBucketRows}
                              rowKey="key"
                              pagination={{ pageSize: 5, showSizeChanger: false }}
                              columns={[
                                { title: '任务分桶', dataIndex: 'bucket' },
                                { title: 'UCB 拉取', dataIndex: 'total_pulls_ucb', sorter: (a, b) => (a.total_pulls_ucb || 0) - (b.total_pulls_ucb || 0) },
                                { title: 'TS 拉取', dataIndex: 'total_pulls_thompson', sorter: (a, b) => (a.total_pulls_thompson || 0) - (b.total_pulls_thompson || 0) },
                              ]}
                            />
                          </Card>

                          <Card title="Bandit Arm 曲线" style={{ marginTop: 16 }} extra={
                            <Select
                              size="small"
                              style={{ width: 220 }}
                              options={banditBucketOptions}
                              value={banditBucket || undefined}
                              placeholder="选择任务分桶"
                              onChange={setBanditBucket}
                            />
                          }>
                            {selectedBandit ? (
                              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                                <Text type="secondary">UCB pulls: {selectedBandit.total_pulls_ucb || 0} | Thompson pulls: {selectedBandit.total_pulls_thompson || 0}</Text>
                                <Table
                                  dataSource={banditCurveRows}
                                  rowKey="key"
                                  pagination={false}
                                  columns={[
                                    { title: 'Arm', dataIndex: 'arm' },
                                    { title: '平均奖励曲线', dataIndex: 'points', render: (v) => <Sparkline points={v || []} /> },
                                    { title: '末值', dataIndex: 'points', render: (v) => ((v && v.length) ? Number(v[v.length - 1].average_reward).toFixed(4) : '-') },
                                  ]}
                                />
                              </Space>
                            ) : <Text type="secondary">暂无 Bandit 分桶</Text>}
                          </Card>
                        </Col>
                      </Row>
                    </div>
                  ),
                },
              ]}
            />
          </Content>
        </Layout>

        <Drawer title="会话列表" open={sessionDrawerOpen} onClose={() => setSessionDrawerOpen(false)} placement="left" width={300}>
          {sessionListNode}
        </Drawer>

        <Drawer title="最近一次执行详情" open={drawerOpen} onClose={() => setDrawerOpen(false)} width={720}>
          {activeSession?.lastPayload ? (
            <>
              <Text strong>回复</Text>
              <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{activeSession.lastPayload.reply}</Paragraph>
              <Divider />
              <Text strong>原始返回</Text>
              <pre className="chat-code-block" style={{ maxHeight: 420 }}>{JSON.stringify(activeSession.lastPayload, null, 2)}</pre>
            </>
          ) : (
            <Empty description="暂无执行详情" />
          )}
        </Drawer>
      </Layout>
    </ConfigProvider>
  )
}
