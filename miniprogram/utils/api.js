// utils/api.js —— 统一的请求封装
// 小程序里没有 CORS，但要求域名在白名单；开发阶段可在开发者工具里关闭校验。

function baseUrl() {
  const app = getApp()
  return (app && app.globalData && app.globalData.baseUrl) || 'http://127.0.0.1:8766'
}

function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: baseUrl() + path,
      method: options.method || 'GET',
      data: options.data,
      header: { 'Content-Type': 'application/json' },
      timeout: options.timeout || 120000,   // 大模型生成要 30~60 秒
      success(res) {
        const d = res.data || {}
        if (res.statusCode >= 200 && res.statusCode < 300 && d.ok !== false) {
          resolve(d)
        } else {
          reject(new Error(d.error || ('HTTP ' + res.statusCode)))
        }
      },
      fail(err) {
        reject(new Error(err.errMsg || '网络请求失败'))
      }
    })
  })
}

module.exports = {
  baseUrl,
  health: () => request('/api/health'),
  options: () => request('/api/options'),
  plan: (body) => request('/api/plan', { method: 'POST', data: body }),
  trip: (id) => request('/api/trips/' + encodeURIComponent(id)),
  trips: () => request('/api/trips'),
  poiInfo: (city, name) =>
    request('/api/poi-info?city=' + encodeURIComponent(city) + '&name=' + encodeURIComponent(name))
}
