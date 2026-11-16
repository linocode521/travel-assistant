// pages/result/result.js —— 结果页：行程 + 地图 + 预算
const api = require('../../utils/api')

// 小程序 JSCore 的 toLocaleString 不可靠，手写千分位
function money(n) {
  const v = Math.round(Number(n) || 0)
  return '¥' + String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

Page({
  data: {
    trip: null,
    loading: true,
    error: '',
    openDays: {},
    kpis: [],
    budgetCells: [],
    markers: [],
    polylines: [],
    center: { latitude: 39.9087, longitude: 116.3975 },
    scale: 12,
    mapNote: '',
    upgrading: false,
    upgradeFailed: ''
  },

  onLoad(query) {
    const app = getApp()

    // 首页若在后台跑 AI，完成后会回调这里
    app.globalData.onUpgrade = (trip) => {
      if (!trip) {
        const msg = app.globalData.upgradeError || 'AI 升级失败'
        this.setData({ upgradeFailed: msg, upgrading: false })
        return
      }
      this.render(trip)
      this.setData({ upgrading: false, upgradeFailed: '' })
      wx.showToast({ title: '已升级为 AI 规划', icon: 'none', duration: 2000 })
    }
    this.setData({ upgrading: !!app.globalData.upgrading })

    const cached = app.globalData.trip

    if (cached && (!query.id || cached.id === query.id)) {
      this.render(cached)
      return
    }
    if (!query.id) {
      // 没有 id 也没有缓存：拉最近一条
      api.trips().then((d) => {
        if (!d.trips.length) throw new Error('还没有行程，先回首页生成一份')
        return api.trip(d.trips[0].id)
      }).then((d) => this.render(d.trip))
        .catch((e) => this.setData({ loading: false, error: e.message }))
      return
    }
    api.trip(query.id)
      .then((d) => this.render(d.trip))
      .catch((e) => this.setData({ loading: false, error: e.message }))
  },

  render(trip) {
    const kpis = [
      { v: money(trip.budget.total), l: '总预算' },
      { v: money(trip.budget.per_person), l: '人均' },
      { v: (trip.stats.spots || 0) + ' 个', l: '景点 · ' + (trip.stats.meals || 0) + ' 餐' },
      { v: Math.round(trip.stats.km || 0) + ' km', l: '市内移动' }
    ]

    const budgetCells = (trip.budget.items || [])
      .filter((x) => x.amount > 0)
      .map((x) => ({ label: x.label, amount: money(x.amount) }))

    const map = this.buildMap(trip)
    const first = map.markers[0]

    const openDays = {}
    if (trip.days.length) openDays[trip.days[0].index] = true

    this.setData({
      trip,
      loading: false,
      kpis,
      budgetCells,
      markers: map.markers,
      polylines: map.lines,
      center: first
        ? { latitude: first.latitude, longitude: first.longitude }
        : { latitude: 39.9087, longitude: 116.3975 },
      mapNote: '共 ' + map.markers.length + ' 个景点，虚线为当日路线'
    })
    wx.setNavigationBarTitle({ title: trip.title || '行程' })
  },

  // 把行程转成小程序 map 组件要的 markers / polyline
  buildMap(trip) {
    const markers = []
    const lines = []
    let mid = 0
    trip.days.forEach((day) => {
      let seq = 0
      const pts = []
      day.items.forEach((it) => {
        if (it.kind === 'hotel') return
        const lat = it.lat_g || it.lat
        const lon = it.lon_g || it.lon
        if (!lat || !lon) return
        pts.push({ latitude: lat, longitude: lon })
        if (it.kind === 'spot') {
          seq += 1
          mid += 1
          markers.push({
            id: mid,
            latitude: lat,
            longitude: lon,
            width: 1,
            height: 1,
            callout: {
              content: String(seq),
              display: 'ALWAYS',
              color: '#FFFFFF',
              bgColor: '#1050E0',
              fontSize: 11,
              padding: 4,
              borderRadius: 0
            }
          })
        }
      })
      if (pts.length > 1) {
        lines.push({
          points: pts,
          color: '#1050E0CC',
          width: 3,
          dottedLine: true
        })
      }
    })
    return { markers, lines }
  },

  toggleDay(e) {
    const idx = Number(e.currentTarget.dataset.index)
    const open = Object.assign({}, this.data.openDays)
    open[idx] = !open[idx]
    this.setData({ openDays: open })
  },

  onBack() {
    wx.navigateBack({ delta: 1, fail() { wx.reLaunch({ url: '/pages/home/home' }) } })
  },

  onCalloutTap(e) {
    const m = this.data.markers.find((x) => x.id === Number(e.detail.markerId))
    if (m) wx.showToast({ title: '第 ' + m.callout.content + ' 站', icon: 'none' })
  },

  onUnload() {
    const app = getApp()
    if (app.globalData.onUpgrade) app.globalData.onUpgrade = null
  },

  onShareAppMessage() {
    const t = this.data.trip
    return { title: t ? t.title : '智能旅行助手', path: '/pages/home/home' }
  }
})
