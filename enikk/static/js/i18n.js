// i18n module - translations and language utilities

const translations = {
  'zh-CN': {
    config: {
      title: '配置', model: '模型', default_model: '默认模型', provider: '提供商',
      base_url: 'API 地址', api_key: 'API 密钥', max_tokens: '最大令牌数', context_length: '上下文长度',
      context_length_auto: '自动', context_length_custom: '自定义',
      context_length_builtin_hint: '选择内置 provider 建议选择「自动」',
      testing: '测试中...', test_connection: '测试连接',
      connection_successful: '✓ 连接成功', connection_failed: '✗ 连接失败',
      im_platforms: '即时通讯平台', enabled: '启用', app_id: '应用 ID',
      client_secret: '客户端密钥', workspace: '工作区', screenshot_dir: '截图目录',
      browse_dir: '浏览目录', open_in_explorer: '在文件管理器中打开',
      weights_dir: '权重目录', max_screenshot_dim: '最大截图尺寸',
      max_iterations: '最大迭代次数',
      logging: '日志', log_level: '日志级别', loading: '正在加载配置...',
      cancel: '取消', save: '保存', saving: '保存中...',
      saved_restart: '配置已保存，重启程序后生效',
      failed_load: '加载配置失败', failed_save: '保存配置失败',
      tab_basic: '基本配置', tab_apps: '应用配置', tab_advanced: '高级配置', tab_im: '即时通讯',
      basic_tip: '💡 配置 AI 模型的 API 信息。支持 OpenAI 兼容的 API（如 OpenAI、Azure OpenAI、本地模型等）。',
      im_tip: '💡 可选配置。如果你想通过即时通讯平台（如 QQ、钉钉）与 Agent 交互，可以在这里配置对应的平台信息。',
      show: '查看', hide: '隐藏', qq_open_platform: 'QQ开放平台',
      close_behavior: '关闭行为', close_behavior_ask: '每次询问',
      close_behavior_minimize: '最小化到托盘', close_behavior_close: '直接关闭',
      close_behavior_tip: '💡 点击窗口关闭按钮时的行为。选择「最小化到托盘」后，程序会常驻系统托盘，可通过托盘图标重新打开窗口。',
    },
    sidebar: {
      new_chat: '新对话', collapse: '折叠侧边栏', no_conversations: '暂无对话',
      im_status: '即时通讯连接状态', connected: '已连接', disconnected: '未连接',
      dashboard: '控制台', refresh: '刷新', open_home: '打开 Home 目录', settings: '设置',
      language: '语言', rename: '重命名', delete: '删除', rename_failed: '重命名失败',
      confirm_delete: '确定要删除对话「{title}」吗？',
      update_available: '有新版本 v{0}，点击查看',
    },
    chat: {
      toggle_thinking: '切换思考过程', toggle_tool_calls: '切换工具调用',
      welcome_title: '有什么我可以帮您的？', welcome_subtitle: '开始对话，探索无限可能',
      load_more: '加载更多...', thinking: '思考中...', thought: '思考过程',
      call: '调用', step: '步骤', copy: '复制', message_placeholder: '输入消息...',
      stop: '停止', send: '发送',
      stop_hint: '🛑 发送 "/stop" 停止当前任务',
      teach_hint: '👆 Agent 找不到按钮？你可以教它：截图中的 [244, 234] 就是坐标，告诉它「点击 [244, 234]」即可。',
      images_hint: '📷 IM 里发送 "/images" 可以开关图片的回显',
      admin_hint: '🔐 请使用管理员权限运行 Enikk，如此它才能启动 app 进程。',
      mouse_hint: '🖱️ Enikk 运行过程中会挪动鼠标指针哦，建议使用 IM 遥控 Enikk，这样你们两就不会因为抢鼠标而吵架',
      mouse_cursor_tip: '💡 图片中的红色十字表示鼠标当前位置'
    },
    time: { today: '今天', yesterday: '昨天', last_7_days: '最近7天', older: '更早' },
    apps: {
      empty: '还没有配置应用', add: '添加应用', edit: '编辑应用',
      name: '名称', path: '路径', advanced: '高级设置',
      launcher_path: '启动器路径', timeout: '启动超时 (秒)',
      name_required: '请输入应用名称', path_required: '请选择可执行文件',
      save_failed: '保存失败', delete_failed: '删除失败',
      confirm_delete: '确定要删除应用 {name} 吗？',
      description_title: '应用配置说明',
      description_body: '在此注册应用后，AI Agent 可以通过名称快速启动它们。当你告诉 Agent "打开 XXX" 时，它会自动查找已注册的应用并执行完整的启动流程（包括启动器登录、等待加载等）。',
      description_tip: '💡 你也可以直接告诉 Agent 添加应用，它会自动调用 register_app 工具完成注册。',
      advanced_warning: '⚠️ 以下配置项通常无需修改，仅在特殊情况下调整'
    },
    memory: {
      title: '学习配置',
      memory_enabled: '启用自动学习',
      memory_enabled_desc: 'Agent 会在后台自动总结经验',
      nudge_interval: '经验总结间隔',
      nudge_interval_desc: '每 N 次对话后触发经验总结',
      creation_nudge_interval: '技能总结间隔',
      creation_nudge_interval_desc: '每 N 次工具调用后触发技能总结',
    },
    status: {
      icon_finder: 'Icon Finder', ocr: 'OCR', im: 'IM', connected: '已连接', disconnected: '未连接', not_configured: '未配置'
    },
    confirm: {
      cancel: '取消', delete: '删除'
    },
    picker: {
      launch: '选择窗口', change: '切换窗口', launching: '正在启动...', tools: '工具',
      success: '✓ 已绑定窗口: {title}', launch_failed: '启动窗口选择器失败',
      unpick_failed: '解绑窗口失败',
    }
  },
  'en': {
    config: {
      title: 'Configuration', model: 'Model', default_model: 'Default Model',
      provider: 'Provider', base_url: 'Base URL', api_key: 'API Key', max_tokens: 'Max Tokens', context_length: 'Context Length',
      context_length_auto: 'Auto', context_length_custom: 'Custom',
      context_length_builtin_hint: 'Recommended to use "Auto" for built-in providers',
      testing: 'Testing...', test_connection: 'Test Connection',
      connection_successful: '✓ Connection successful', connection_failed: '✗ Connection failed',
      im_platforms: 'IM Platforms', enabled: 'Enabled', app_id: 'App ID',
      client_secret: 'Client Secret', workspace: 'Workspace', screenshot_dir: 'Screenshot Directory',
      browse_dir: 'Browse directory', open_in_explorer: 'Open in file explorer',
      weights_dir: 'Weights Directory', max_screenshot_dim: 'Max Screenshot Dimension',
      max_iterations: 'Max Iterations',
      logging: 'Logging', log_level: 'Log Level', loading: 'Loading configuration...',
      cancel: 'Cancel', save: 'Save', saving: 'Saving...',
      saved_restart: 'Configuration saved, restart to take effect',
      failed_load: 'Failed to load configuration', failed_save: 'Failed to save configuration',
      tab_basic: 'Basic', tab_apps: 'Apps', tab_advanced: 'Advanced', tab_im: 'IM',
      basic_tip: '💡 Configure your AI model API settings. Supports OpenAI-compatible APIs (OpenAI, Azure OpenAI, local models, etc.).',
      im_tip: '💡 Optional. If you want to interact with the Agent via IM platforms (like QQ, DingTalk), configure them here.',
      show: 'Show', hide: 'Hide', qq_open_platform: 'QQ Open Platform',
      close_behavior: 'Close Behavior', close_behavior_ask: 'Ask every time',
      close_behavior_minimize: 'Minimize to tray', close_behavior_close: 'Close app',
      close_behavior_tip: '💡 What happens when you click the close button. With "Minimize to tray", the app stays running in the system tray and can be reopened from there.',
    },
    sidebar: {
      new_chat: 'New Chat', collapse: 'Collapse sidebar', no_conversations: 'No conversations yet',
      im_status: 'IM Bridge connection status', connected: 'Connected', disconnected: 'Disconnected',
      dashboard: 'dashboard', refresh: 'Refresh', open_home: 'Open Home directory', settings: 'Settings',
      language: 'Language', rename: 'Rename', delete: 'Delete', rename_failed: 'Rename failed',
      confirm_delete: 'Delete conversation "{title}"?',
      update_available: 'New version v{0} available, click to view',
    },
    chat: {
      toggle_thinking: 'Toggle thinking', toggle_tool_calls: 'Toggle tool calls',
      welcome_title: 'What can I help you with?', welcome_subtitle: 'Start a conversation and explore infinite possibilities',
      load_more: 'Load more...', thinking: 'Thinking...', thought: 'Thought',
      call: 'call', step: 'Step', copy: 'Copy', message_placeholder: 'Message Enikk',
      stop: 'Stop', send: 'Send',
      stop_hint: '🛑 Send "/stop" to stop current task',
      teach_hint: '👆 Agent can\'t find the button? You can teach it: [244, 234] in the screenshot is the coordinate. Tell it "click [244, 234]".',
      images_hint: '📷 Send "/images" in IM to toggle image display',
      admin_hint: '🔐 Please run Enikk as administrator so it can launch app processes.',
      mouse_hint: '🖱️ Enikk will move the mouse pointer during operation. Consider using IM to control it remotely, so you won\'t fight over the mouse',
      mouse_cursor_tip: '💡 The red crosshair in the image indicates the current mouse position'
    },
    time: { today: 'Today', yesterday: 'Yesterday', last_7_days: 'Last 7 days', older: 'Older' },
    apps: {
      empty: 'No apps configured yet', add: 'Add App', edit: 'Edit App',
      name: 'Name', path: 'Path', advanced: 'Advanced Settings',
      launcher_path: 'Launcher Path', timeout: 'Launch Timeout (seconds)',
      name_required: 'Please enter app name', path_required: 'Please select executable file',
      save_failed: 'Save failed', delete_failed: 'Delete failed',
      confirm_delete: 'Are you sure you want to delete app {name}?',
      description_title: 'About App Configuration',
      description_body: 'Register your apps here so the AI Agent can launch them by name. When you tell the Agent to "open XXX", it automatically finds the registered app and executes the full launch flow (including launcher login, loading screens, etc.).',
      description_tip: '💡 You can also ask the Agent to add apps directly — it will call the register_app tool automatically.',
      advanced_warning: '⚠️ These settings typically do not need to be modified. Only adjust if you know what you are doing.'
    },
    memory: {
      title: 'Learning',
      memory_enabled: 'Enable Auto Learning',
      memory_enabled_desc: 'Agent will summarize experiences in the background',
      nudge_interval: 'Experience Summary Interval',
      nudge_interval_desc: 'Trigger experience summary every N conversations',
      creation_nudge_interval: 'Skill Summary Interval',
      creation_nudge_interval_desc: 'Trigger skill summary every N tool calls',
    },
    status: {
      icon_finder: 'Icon Finder', ocr: 'OCR', im: 'IM', connected: 'Connected', disconnected: 'Disconnected', not_configured: 'Not configured'
    },
    confirm: {
      cancel: 'Cancel', delete: 'Delete'
    },
    picker: {
      launch: 'Pick Window', change: 'Change Window', launching: 'Launching...', tools: 'Tools',
      success: '✓ Bound to window: {title}', launch_failed: 'Failed to launch window picker',
      unpick_failed: 'Failed to unbind window',
    }
  }
};

function resolveLang(lang) {
  if (translations[lang]) return lang;
  const prefix = lang.split('-')[0];
  for (const key of Object.keys(translations)) {
    if (key.startsWith(prefix)) return key;
  }
  console.warn('[i18n] Unsupported language, falling back to default:', lang);
  return null;
}

let currentLang = 'zh-CN';

// Read language from URL parameter (passed by backend)
const urlLang = new URLSearchParams(window.location.search).get('lang');
if (urlLang) {
  const resolved = resolveLang(urlLang);
  if (resolved) {
    currentLang = resolved;
    console.log('[i18n] Loaded language from URL:', currentLang);
  }
}

function t(key, ...args) {
  const keys = key.split('.');
  let value = translations[currentLang];

  for (const k of keys) {
    if (value && typeof value === 'object') {
      value = value[k];
    } else {
      return key;
    }
  }

  if (value === undefined) return key;

  if (args.length > 0 && typeof value === 'string') {
    return value.replace(/\{(\d+)\}/g, (match, index) => {
      return args[parseInt(index)] !== undefined ? args[parseInt(index)] : match;
    });
  }

  return value;
}

function setLang(lang) {
  const resolved = resolveLang(lang);
  if (resolved) {
    currentLang = resolved;
    window.dispatchEvent(new CustomEvent('language-changed'));
  }
}
