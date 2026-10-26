/**
 * 全局主题系统：实色卡片基准，对齐 angel_brush。
 * - A 色（边框/分隔线）唯一真相源：tokens.light/dark.divider
 * - 背景/侧栏/卡片三色统一：bgPage / bgSider / bgCard
 */
import type { GlobalThemeOverrides } from 'naive-ui'
import type { ComputedRef, InjectionKey, Ref } from 'vue'
import { computed, ref } from 'vue'

export type ThemeMode = 'light' | 'dark'

const THEME_STORAGE_KEY = 'angel-heart-theme'

export interface ThemeApi {
  mode: Ref<ThemeMode>
  isDark: ComputedRef<boolean>
  toggle: () => void
  /** 主题是否由宿主 AstrBot 控制（嵌入模式下禁用页面内切换按钮） */
  followedByHost: Ref<boolean>
}

export const themeKey: InjectionKey<ThemeApi> = Symbol('app-theme')

/** AstrBot 插件页桥接对象；新旧两代命名都要认（宿主 4.x 起改名 PluginView）。 */
interface HostBridge {
  onContext?: (handler: (ctx: { isDark?: boolean } | null) => void) => () => void
  getContext?: () => { isDark?: boolean } | null
}

function getHostBridge(): HostBridge | null {
  if (typeof window === 'undefined') return null
  const holder = window as unknown as Record<string, unknown>
  const bridge = (holder.AstrBotPluginView || holder.AstrBotPluginPage) as HostBridge | undefined
  return bridge && typeof bridge === 'object' ? bridge : null
}

function normalizeMode(value: unknown): ThemeMode | null {
  return value === 'dark' || value === 'light' ? value : null
}

/** 宿主桥接上下文里的 isDark 转 ThemeMode；非布尔（含未就绪）返回 null。 */
function modeFromIsDark(value: unknown): ThemeMode | null {
  if (typeof value !== 'boolean') return null
  return value ? 'dark' : 'light'
}

export function loadThemeMode(): ThemeMode {
  // 优先级：宿主 URL 参数 > 宿主桥接注入的 data-theme > 页面自身持久化
  // 宿主是唯一真相源：嵌入时若用户上次在页面内切过，也不能盖掉 AstrBot 的选择。
  try {
    const fromUrl = normalizeMode(new URLSearchParams(window.location.search).get('theme'))
    if (fromUrl) return fromUrl
  } catch {
    /* URL 解析失败继续往下走 */
  }

  try {
    const fromHost = normalizeMode(document.documentElement.dataset.theme)
    if (fromHost) return fromHost
  } catch {
    /* 无 document（极端环境）时继续往下走 */
  }

  try {
    return localStorage.getItem(THEME_STORAGE_KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

function saveThemeMode(mode: ThemeMode) {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    /* 忽略持久化失败 */
  }
}

export function createThemeApi(): ThemeApi {
  const mode = ref<ThemeMode>(loadThemeMode())
  const followedByHost = ref<boolean>(false)

  const bridge = getHostBridge()
  if (bridge?.onContext) {
    try {
      bridge.onContext((ctx) => {
        const next = modeFromIsDark(ctx?.isDark)
        if (!next) return
        // 一旦收到宿主推送，后续主题完全交给宿主，页面内切换不再写 localStorage 覆盖它。
        followedByHost.value = true
        mode.value = next
      })
      const initial = modeFromIsDark(bridge.getContext?.()?.isDark)
      if (initial) {
        followedByHost.value = true
        mode.value = initial
      }
    } catch {
      /* 桥接异常时退回页面自管主题 */
    }
  }

  return {
    mode,
    isDark: computed(() => mode.value === 'dark'),
    followedByHost,
    toggle: () => {
      mode.value = mode.value === 'light' ? 'dark' : 'light'
      saveThemeMode(mode.value)
    },
  }
}

const brand = {
  light: { base: '#007aff', hover: '#3395ff', pressed: '#0062cc', suppl: '#3395ff' },
  dark: { base: '#0a84ff', hover: '#409cff', pressed: '#0069cc', suppl: '#409cff' },
}

// A 色与面色：亮/暗各一套，theme.ts 为唯一真相源，App.vue 的 CSS 变量需与此对齐
const tokens = {
  light: {
    bgPage: '#F5F5F5',
    bgSider: '#ffffff',
    bgCard: '#ffffff',
    divider: 'rgba(60, 60, 67, 0.12)',
  },
  dark: {
    bgPage: '#101014',
    bgSider: '#18181c',
    bgCard: '#18181c',
    divider: 'rgba(84, 84, 88, 0.4)',
  },
} as const

export function buildThemeOverrides(mode: ThemeMode): GlobalThemeOverrides {
  const c = brand[mode]
  const t = tokens[mode]
  return {
    common: {
      primaryColor: c.base,
      primaryColorHover: c.hover,
      primaryColorPressed: c.pressed,
      primaryColorSuppl: c.suppl,
      fontSize: '15px',
      borderRadius: '10px',
      borderRadiusSmall: '8px',
      bodyColor: t.bgPage,
      cardColor: t.bgCard,
      modalColor: t.bgCard,
      popoverColor: t.bgCard,
      dividerColor: t.divider,
      borderColor: t.divider,
    },
    Button: {
      borderRadius: '999px',
    },
    Layout: {
      color: t.bgPage,
      siderColor: t.bgSider,
    },
    Card: {
      color: t.bgCard,
      colorEmbedded: t.bgCard,
      borderColor: t.divider,
    },
  }
}
