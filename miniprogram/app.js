// app.js —— 全局状态：后端地址 + 最近一次生成的行程
App({
  globalData: {
    // 开发阶段：指向本机 Flask 服务。手机预览时改成电脑的局域网 IP，
    // 并在微信开发者工具「详情 → 本地设置」勾选「不校验合法域名」。
    baseUrl: 'http://192.168.218.120:8766',
    trip: null,
    options: null
  },

  onLaunch() {
    // 允许被 profile 覆盖（比如换成正式 HTTPS 域名）
    const saved = wx.getStorageSync('baseUrl')
    if (saved) this.globalData.baseUrl = saved
  }
})
