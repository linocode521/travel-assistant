// pages/home/home.js —— 首页：先秒出规则版，后台再升级为 AI 版
const api = require('../../utils/api')

Page({
  data: {
    loading: false,
    options: null,
    cities: [],
    cityIndex: 0,
    date: '',
    days: 3,
    dayOptions: [1, 2, 3, 4, 5, 6, 7],
    styles: [],
    paces: [],
    pace: 'moderate',
    tiers: [],
    tier: 'comfort',
    adults: 2,
    adultsRange: [1, 2, 3, 4, 5, 6],
    children: 0,
    childrenRange: [0, 1, 2, 3],
    origin: '',
    budget: '',
    preference: '',
    ruleMode: false,
    error: ''
  },

  onLoad() {
    const d = new Date(Date.now() + 7 * 86400000)
    this.setData({ date: d.toISOString().slice(0, 10) })

    api.options().then((o) => {
      const cities = o.cities.map((c) => c.city)
      const paces = o.paces.map((p) => ({ key: p.key, label: p.label, hint: p.hint }))
      const tiers = o.tiers.map((t) => ({ key: t.key, label: t.label }))
      const styles = o.styles.map((s) => ({ key: s.key, label: s.label }))
      const picked = o.defaults.styles.slice()
      this.setData({
        options: o,
        cities,
        paces,
        tiers,
        styles: styles.map((x) => Object.assign({}, x, { on: picked.indexOf(x.key) >= 0 })),
        pace: o.defaults.pace,
        tier: o.defaults.tier
      })
    }).catch((e) => {
      this.setData({ error: '连不上后端：' + e.message })
    })
  },

  onCity(e) { this.setData({ cityIndex: Number(e.detail.value) }) },
  onDate(e) { this.setData({ date: e.detail.value }) },
  onDays(e) { this.setData({ days: this.data.dayOptions[Number(e.detail.value)] }) },

  toggleStyle(e) {
    const key = e.currentTarget.dataset.key
    const picked = this.data.styles.filter((x) => x.on).map((x) => x.key)
    const i = picked.indexOf(key)
    if (i >= 0) picked.splice(i, 1)
    else picked.push(key)
    if (!picked.length) picked.push(key)
    this.setData({
      styles: this.data.styles.map((x) => Object.assign({}, x, { on: picked.indexOf(x.key) >= 0 }))
    })
  },

  setPace(e) { this.setData({ pace: e.currentTarget.dataset.key }) },
  setTier(e) { this.setData({ tier: e.currentTarget.dataset.key }) },
  onAdults(e) { this.setData({ adults: this.data.adultsRange[Number(e.detail.value)] }) },
  onChildren(e) { this.setData({ children: this.data.childrenRange[Number(e.detail.value)] }) },
  onOrigin(e) { this.setData({ origin: e.detail.value }) },
  onBudget(e) { this.setData({ budget: e.detail.value }) },
  onPreference(e) { this.setData({ preference: e.detail.value }) },
  onRuleMode(e) { this.setData({ ruleMode: e.detail.value }) },

  buildBody(mode) {
    const picked = this.data.styles.filter((x) => x.on).map((x) => x.key)
    return {
      city: this.data.cities[this.data.cityIndex],
      days: this.data.days,
      start_date: this.data.date,
      styles: picked,
      pace: this.data.pace,
      tier: this.data.tier,
      party: { adults: this.data.adults, children: this.data.children },
      origin: (this.data.origin || '').trim(),
      budget: this.data.budget ? Number(this.data.budget) : null,
      preference: (this.data.preference || '').trim(),
      mode
    }
  },

  onGenerate() {
    if (this.data.loading) return
    if (!this.data.cities.length) {
      wx.showToast({ title: '还没连上后端', icon: 'none' })
      return
    }

    const app = getApp()
    const body = this.buildBody('rule')
    this.setData({ loading: true, error: '' })

    // ---- 第一阶段：规则引擎，0.05 秒出结果
    api.plan(body).then((d) => {
      this.setData({ loading: false })
      app.globalData.trip = d.trip
      wx.navigateTo({ url: '/pages/result/result?id=' + encodeURIComponent(d.trip.id) })

      // ---- 第二阶段：后台跑 AI，完成后覆盖同一条记录
      if (!this.data.ruleMode) this.startUpgrade(d.trip.id)
    }).catch((e) => {
      this.setData({ loading: false, error: '生成失败：' + e.message })
      wx.showToast({ title: '生成失败', icon: 'none' })
    })
  },

  startUpgrade(reuseId) {
    const app = getApp()
    app.globalData.upgrading = true
    app.globalData.upgradeError = ''

    const body = this.buildBody('auto')
    body.reuse_id = reuseId

    api.plan(body).then((d) => {
      app.globalData.trip = d.trip
      app.globalData.upgrading = false
      const cb = app.globalData.onUpgrade
      if (cb) cb(d.trip)
    }).catch((e) => {
      app.globalData.upgrading = false
      app.globalData.upgradeError = e.message
      const cb = app.globalData.onUpgrade
      if (cb) cb(null)
    })
  }
})
