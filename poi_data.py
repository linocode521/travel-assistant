# -*- coding: utf-8 -*-
"""城市 POI 数据库（景点 / 餐饮 / 酒店价位）。

为什么要本地库，而不是让大模型自由发挥：
1. 经纬度必须真实，否则地图会飘到海里；
2. 门票、均价是预算的骨架，模型给的价格经常前后矛盾；
3. 有了库，大模型只需负责"选哪些、怎么排"，事实交给数据。

坐标量级：WGS-84（Leaflet / OpenStreetMap 使用），小数点后 4 位≈11m，
足够做示意路线。价格为人民币，"免费"用 0 表示。
"""

from __future__ import annotations

from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# 景点库
# id, name, lon, lat, ticket(元/人), hours(建议游览小时), tags, open(开放时间), note
# --------------------------------------------------------------------------- #
SPOTS: Dict[str, List[dict]] = {
    "北京": [
        {"id": "bj-gugong", "name": "故宫博物院", "lon": 116.3972, "lat": 39.9163, "ticket": 60, "hours": 3.5,
         "tags": ["历史", "建筑", "必去"], "open": "08:30-17:00（周一闭馆）", "note": "建议提前 7 天在官方小程序预约"},
        {"id": "bj-tiananmen", "name": "天安门广场", "lon": 116.3975, "lat": 39.9087, "ticket": 0, "hours": 0.8,
         "tags": ["地标", "历史"], "open": "05:00-22:00（需安检）", "note": "看升旗需凌晨到场，需带身份证"},
        {"id": "bj-jingshan", "name": "景山公园", "lon": 116.3967, "lat": 39.9285, "ticket": 2, "hours": 1.0,
         "tags": ["登高", "摄影", "性价比"], "open": "06:00-21:00", "note": "万春亭是俯瞰故宫全景的最佳机位"},
        {"id": "bj-tiantan", "name": "天坛公园", "lon": 116.4107, "lat": 39.8822, "ticket": 34, "hours": 2.0,
         "tags": ["历史", "建筑", "园林"], "open": "06:00-22:00（景点 08:00-17:30）", "note": "联票含祈年殿、回音壁"},
        {"id": "bj-yiheyuan", "name": "颐和园", "lon": 116.2731, "lat": 39.9999, "ticket": 30, "hours": 3.0,
         "tags": ["园林", "湖泊", "世界遗产"], "open": "06:30-18:00", "note": "从北宫门进，翻过万寿山就到长廊，人少"},
        {"id": "bj-changcheng", "name": "八达岭长城", "lon": 116.0167, "lat": 40.3567, "ticket": 40, "hours": 4.0,
         "tags": ["世界遗产", "徒步", "必去"], "open": "06:30-19:00", "note": "离市区约 70km，建议一早出发或坐市郊铁路"},
        {"id": "bj-mutianyu", "name": "慕田峪长城", "lon": 116.5667, "lat": 40.4333, "ticket": 45, "hours": 4.5,
         "tags": ["世界遗产", "徒步", "人少"], "open": "07:30-18:00", "note": "比八达岭清静，可坐缆车上、滑道下"},
        {"id": "bj-nanluo", "name": "南锣鼓巷", "lon": 116.4033, "lat": 39.9375, "ticket": 0, "hours": 1.5,
         "tags": ["胡同", "小吃", "夜景"], "open": "全天", "note": "商业化较重，往北的帽儿胡同更原味"},
        {"id": "bj-shichahai", "name": "什刹海", "lon": 116.3839, "lat": 39.9410, "ticket": 0, "hours": 2.0,
         "tags": ["湖泊", "胡同", "夜景"], "open": "全天", "note": "傍晚沿湖走一圈，后海酒吧街很热闹"},
        {"id": "bj-gongwangfu", "name": "恭王府", "lon": 116.3839, "lat": 39.9376, "ticket": 40, "hours": 1.5,
         "tags": ["历史", "建筑"], "open": "08:00-17:00（周一闭馆）", "note": "和珅故居，“福”字碑是镇馆之宝"},
        {"id": "bj-798", "name": "798 艺术区", "lon": 116.4954, "lat": 39.9843, "ticket": 0, "hours": 2.5,
         "tags": ["艺术", "拍照", "文艺"], "open": "10:00-18:00（多数画廊周一闭馆）", "note": "旧厂房改造，适合阴天/下雨备选"},
        {"id": "bj-guomao", "name": "国贸 CBD 观景", "lon": 116.4611, "lat": 39.9089, "ticket": 0, "hours": 1.0,
         "tags": ["现代", "夜景", "城市"], "open": "全天", "note": "国贸商城 4 层露台可看中国尊与央视大楼"},
    ],
    "上海": [
        {"id": "sh-waitan", "name": "外滩", "lon": 121.4900, "lat": 31.2400, "ticket": 0, "hours": 1.5,
         "tags": ["地标", "夜景", "建筑"], "open": "全天", "note": "日落后半小时天光最好，人也最多"},
        {"id": "sh-yuyuan", "name": "豫园", "lon": 121.4922, "lat": 31.2272, "ticket": 40, "hours": 1.5,
         "tags": ["园林", "历史", "小吃"], "open": "09:00-16:30", "note": "出园就是城隍庙，南翔小笼别排主店"},
        {"id": "sh-nanjinglu", "name": "南京路步行街", "lon": 121.4737, "lat": 31.2353, "ticket": 0, "hours": 1.5,
         "tags": ["购物", "夜景"], "open": "全天", "note": "从人民广场一路走到外滩，约 1.5km"},
        {"id": "sh-tianzifang", "name": "田子坊", "lon": 121.4683, "lat": 31.2086, "ticket": 0, "hours": 1.5,
         "tags": ["文艺", "弄堂", "手作"], "open": "10:00-22:00", "note": "弄堂小店密集，工作日人少"},
        {"id": "sh-xintiandi", "name": "新天地", "lon": 121.4740, "lat": 31.2190, "ticket": 0, "hours": 1.5,
         "tags": ["石库门", "餐饮", "夜景"], "open": "全天", "note": "石库门建筑改造，餐厅酒吧集中"},
        {"id": "sh-wukang", "name": "武康路", "lon": 121.4370, "lat": 31.2070, "ticket": 0, "hours": 2.0,
         "tags": ["马路", "拍照", "咖啡"], "open": "全天", "note": "武康大楼 + 梧桐街道，适合慢走半日"},
        {"id": "sh-museum", "name": "上海博物馆", "lon": 121.4750, "lat": 31.2280, "ticket": 0, "hours": 3.0,
         "tags": ["博物馆", "历史", "雨天备选"], "open": "09:00-17:00（周一闭馆）", "note": "免费，需提前预约，青铜器馆必看"},
        {"id": "sh-mocac", "name": "当代艺术博物馆 PSA", "lon": 121.4880, "lat": 31.1880, "ticket": 0, "hours": 2.0,
         "tags": ["艺术", "建筑", "雨天备选"], "open": "11:00-19:00（周一闭馆）", "note": "旧电厂改造，大烟囱是地标"},
        {"id": "sh-jinmao", "name": "陆家嘴三件套观景", "lon": 121.5057, "lat": 31.2396, "ticket": 180, "hours": 1.5,
         "tags": ["地标", "夜景", "登高"], "open": "10:00-21:00", "note": "上海中心 118 层视野最好，旺季提前买票"},
        {"id": "sh-disney", "name": "上海迪士尼乐园", "lon": 121.6570, "lat": 31.1410, "ticket": 475, "hours": 10.0,
         "tags": ["主题乐园", "亲子", "全天"], "open": "08:30-21:30（以官网为准）", "note": "需单独安排一整天，票价随日期浮动"},
    ],
    "杭州": [
        {"id": "hz-xihu", "name": "西湖（断桥—白堤）", "lon": 120.1510, "lat": 30.2590, "ticket": 0, "hours": 3.0,
         "tags": ["湖泊", "必去", "徒步"], "open": "全天", "note": "从断桥出发沿白堤到孤山，清晨人最少"},
        {"id": "hz-sudi", "name": "苏堤春晓", "lon": 120.1410, "lat": 30.2410, "ticket": 0, "hours": 1.5,
         "tags": ["湖泊", "徒步"], "open": "全天", "note": "全长 2.8km，骑行比步行舒服"},
        {"id": "hz-leifeng", "name": "雷峰塔", "lon": 120.1487, "lat": 30.2314, "ticket": 40, "hours": 1.5,
         "tags": ["登高", "历史", "摄影"], "open": "08:00-19:00", "note": "塔顶看西湖全景 + 日落，最佳时段 16:30 后"},
        {"id": "hz-lingyin", "name": "灵隐寺·飞来峰", "lon": 120.1010, "lat": 30.2420, "ticket": 30, "hours": 2.5,
         "tags": ["寺庙", "历史", "自然"], "open": "07:00-17:30", "note": "飞来峰 30 元 + 灵隐寺 30 元，需分别买"},
        {"id": "hz-longjing", "name": "龙井村茶园", "lon": 120.1040, "lat": 30.2250, "ticket": 0, "hours": 2.0,
         "tags": ["茶园", "慢游", "拍照"], "open": "全天", "note": "从龙井村走到九溪十八涧，春天最佳"},
        {"id": "hz-hefang", "name": "河坊街", "lon": 120.1690, "lat": 30.2440, "ticket": 0, "hours": 1.5,
         "tags": ["老街", "小吃", "夜景"], "open": "全天", "note": "胡庆余堂、王星记扇庄在这条街上"},
        {"id": "hz-xixi", "name": "西溪湿地", "lon": 120.0700, "lat": 30.2680, "ticket": 80, "hours": 3.5,
         "tags": ["湿地", "自然", "慢游"], "open": "08:00-17:30", "note": "大园区，建议坐电瓶船节省体力"},
        {"id": "hz-qiantang", "name": "钱江新城灯光秀", "lon": 120.2120, "lat": 30.2460, "ticket": 0, "hours": 1.0,
         "tags": ["夜景", "现代"], "open": "19:00-21:00（周五至周日）", "note": "城市阳台看江景与灯光秀"},
    ],
    "成都": [
        {"id": "cd-panda", "name": "成都大熊猫繁育研究基地", "lon": 104.1470, "lat": 30.7330, "ticket": 55, "hours": 3.0,
         "tags": ["动物", "必去", "亲子"], "open": "07:30-18:00", "note": "必须早上去，9 点后熊猫基本回笼睡觉"},
        {"id": "cd-kuanzhai", "name": "宽窄巷子", "lon": 104.0550, "lat": 30.6660, "ticket": 0, "hours": 2.0,
         "tags": ["老街", "小吃", "拍照"], "open": "全天", "note": "井巷子人最少，晚上有灯"},
        {"id": "cd-jinli", "name": "锦里古街", "lon": 104.0470, "lat": 30.6470, "ticket": 0, "hours": 1.5,
         "tags": ["老街", "小吃", "夜景"], "open": "全天", "note": "紧邻武侯祠，傍晚灯笼亮起最好看"},
        {"id": "cd-wuhou", "name": "武侯祠", "lon": 104.0480, "lat": 30.6480, "ticket": 50, "hours": 1.5,
         "tags": ["历史", "三国"], "open": "08:00-18:00", "note": "三国的朋友别错过，红墙竹影适合拍照"},
        {"id": "cd-dufu", "name": "杜甫草堂", "lon": 104.0300, "lat": 30.6610, "ticket": 50, "hours": 2.0,
         "tags": ["历史", "园林", "文学"], "open": "08:00-18:30", "note": "园子很静，适合慢慢逛"},
        {"id": "cd-chunxi", "name": "春熙路·太古里", "lon": 104.0800, "lat": 30.6530, "ticket": 0, "hours": 2.0,
         "tags": ["购物", "夜景", "城市"], "open": "全天", "note": "IFS 楼顶爬墙熊猫是打卡点"},
        {"id": "cd-wenshu", "name": "文殊院", "lon": 104.0730, "lat": 30.6770, "ticket": 0, "hours": 1.5,
         "tags": ["寺庙", "小吃", "慢游"], "open": "08:00-17:00", "note": "旁边就是洞子口张老二凉粉"},
        {"id": "cd-qingcheng", "name": "青城山", "lon": 103.5670, "lat": 30.9000, "ticket": 80, "hours": 5.0,
         "tags": ["自然", "道教", "徒步"], "open": "08:00-17:00", "note": "前山轻松后山野，需安排一整天"},
        {"id": "cd-doo", "name": "都江堰", "lon": 103.6170, "lat": 31.0020, "ticket": 80, "hours": 3.5,
         "tags": ["历史", "水利", "自然"], "open": "08:00-17:30", "note": "可和青城山同一天（离堆公园出来坐动车）"},
    ],
    "西安": [
        {"id": "xa-bingmayong", "name": "秦始皇兵马俑", "lon": 109.2780, "lat": 34.3850, "ticket": 120, "hours": 3.5,
         "tags": ["世界遗产", "必去", "历史"], "open": "08:30-17:00", "note": "建议请讲解，否则就是三个大坑"},
        {"id": "xa-chengqiang", "name": "西安城墙", "lon": 108.9450, "lat": 34.2610, "ticket": 54, "hours": 2.0,
         "tags": ["历史", "骑行", "夜景"], "open": "08:00-22:00", "note": "租自行车绕一圈 13.7km，约 1.5 小时"},
        {"id": "xa-dayanta", "name": "大雁塔·大唐不夜城", "lon": 108.9640, "lat": 34.2180, "ticket": 50, "hours": 2.5,
         "tags": ["历史", "夜景", "步行街"], "open": "08:00-21:00（街区全天）", "note": "晚上 19:00 后有巡游表演"},
        {"id": "xa-huimin", "name": "回民街", "lon": 108.9470, "lat": 34.2660, "ticket": 0, "hours": 1.5,
         "tags": ["小吃", "夜宵", "市井"], "open": "全天", "note": "主街贵，往里走到洒金桥更本地"},
        {"id": "xa-shanbo", "name": "陕西历史博物馆", "lon": 108.9530, "lat": 34.2220, "ticket": 0, "hours": 3.0,
         "tags": ["博物馆", "历史", "雨天备选"], "open": "09:00-17:30（周一闭馆）", "note": "免费但要提前预约，国宝厅值得单看"},
        {"id": "xa-huaqing", "name": "华清宫", "lon": 109.2160, "lat": 34.3630, "ticket": 120, "hours": 2.5,
         "tags": ["历史", "温泉", "演出"], "open": "07:00-18:00", "note": "和兵马俑同线，可买联票"},
        {"id": "xa-datangfurong", "name": "大唐芙蓉园", "lon": 108.9730, "lat": 34.2090, "ticket": 120, "hours": 3.0,
         "tags": ["园林", "夜景", "演出"], "open": "09:00-22:00", "note": "晚上水幕表演，票偏贵看取舍"},
    ],
    "广州": [
        {"id": "gz-xiaomanyao", "name": "广州塔", "lon": 113.3245, "lat": 23.1066, "ticket": 150, "hours": 1.5,
         "tags": ["地标", "夜景", "登高"], "open": "09:00-22:30", "note": "摩天轮套票更贵，江对岸拍塔更好看"},
        {"id": "gz-chenjiaci", "name": "陈家祠", "lon": 113.2460, "lat": 23.1290, "ticket": 10, "hours": 1.5,
         "tags": ["建筑", "历史", "性价比"], "open": "09:00-17:00", "note": "岭南木雕砖雕看这里，30 分钟看完精华"},
        {"id": "gz-shamian", "name": "沙面岛", "lon": 113.2450, "lat": 23.1070, "ticket": 0, "hours": 1.5,
         "tags": ["建筑", "拍照", "慢游"], "open": "全天", "note": "欧陆建筑群，适合清晨或傍晚拍照"},
        {"id": "gz-baiyun", "name": "白云山", "lon": 113.2900, "lat": 23.1830, "ticket": 5, "hours": 3.0,
         "tags": ["自然", "徒步", "登高"], "open": "06:00-21:00", "note": "摩星岭看全城，索道可省一半体力"},
        {"id": "gz-guangbota", "name": "光孝寺", "lon": 113.2530, "lat": 23.1290, "ticket": 5, "hours": 1.0,
         "tags": ["寺庙", "历史"], "open": "06:30-17:00", "note": "广州最古老的寺庙之一"},
        {"id": "gz-yongqingfang", "name": "永庆坊", "lon": 113.2410, "lat": 23.1180, "ticket": 0, "hours": 1.5,
         "tags": ["老街", "文艺", "夜景"], "open": "全天", "note": "骑楼老街改造，粤剧艺术博物馆在旁"},
    ],
}

# --------------------------------------------------------------------------- #
# 餐饮库：早餐/午餐/晚餐候选，price 为人均（元）
# --------------------------------------------------------------------------- #
EATERIES: Dict[str, List[dict]] = {
    "北京": [
        {"id": "bj-r-kaoya", "name": "四季民福烤鸭店（故宫店）", "lon": 116.4042, "lat": 39.9163, "price": 130,
         "cuisine": "北京菜", "meal": ["dinner"], "dish": "烤鸭、芥末鸭掌", "note": "看故宫角楼，需排号"},
        {"id": "bj-r-quanjude", "name": "全聚德（前门店）", "lon": 116.3980, "lat": 39.8993, "price": 180,
         "cuisine": "北京菜", "meal": ["lunch", "dinner"], "dish": "挂炉烤鸭", "note": "老字号，游客多"},
        {"id": "bj-r-huguosi", "name": "护国寺小吃（护国寺总店）", "lon": 116.3770, "lat": 39.9370, "price": 25,
         "cuisine": "小吃", "meal": ["breakfast", "lunch"], "dish": "豆汁焦圈、艾窝窝、面茶", "note": "本地早点，豆汁慎点"},
        {"id": "bj-r-zhajiang", "name": "海碗居炸酱面", "lon": 116.3460, "lat": 39.9330, "price": 45,
         "cuisine": "面食", "meal": ["lunch"], "dish": "老北京炸酱面、豌豆黄", "note": "份量大，两人一碗面足够"},
        {"id": "bj-r-nanmen", "name": "南门涮肉（什刹海店）", "lon": 116.3850, "lat": 39.9420, "price": 110,
         "cuisine": "火锅", "meal": ["dinner"], "dish": "铜锅涮肉、麻酱小料", "note": "冬天首选，提前取号"},
        {"id": "bj-r-baodu", "name": "紫光园（朝阳门店）", "lon": 116.4340, "lat": 39.9240, "price": 60,
         "cuisine": "清真", "meal": ["lunch", "dinner"], "dish": "烤鸭、爆肚、糖火烧", "note": "性价比高，本地人常去"},
        {"id": "bj-r-shanxi", "name": "老门框百年卤煮", "lon": 116.3900, "lat": 39.8930, "price": 35,
         "cuisine": "小吃", "meal": ["lunch", "dinner"], "dish": "卤煮火烧、炒肝", "note": "重口味但地道"},
    ],
    "上海": [
        {"id": "sh-r-nanxiang", "name": "南翔馒头店（豫园）", "lon": 121.4920, "lat": 31.2270, "price": 60,
         "cuisine": "本帮点心", "meal": ["lunch"], "dish": "蟹粉小笼、灌汤包", "note": "楼上堂食比一楼排队快"},
        {"id": "sh-r-laofandian", "name": "上海老饭店", "lon": 121.4920, "lat": 31.2260, "price": 130,
         "cuisine": "本帮菜", "meal": ["lunch", "dinner"], "dish": "八宝鸭、油爆虾、草头圈子", "note": "老字号本帮味"},
        {"id": "sh-r-jiajiatangbao", "name": "佳家汤包（黄河路）", "lon": 121.4720, "lat": 31.2380, "price": 40,
         "cuisine": "点心", "meal": ["breakfast", "lunch"], "dish": "鲜肉汤包、蟹粉汤包", "note": "早去不排队"},
        {"id": "sh-r-wujiang", "name": "小杨生煎（吴江路）", "lon": 121.4660, "lat": 31.2330, "price": 35,
         "cuisine": "小吃", "meal": ["breakfast", "lunch"], "dish": "生煎、咖喱牛肉汤", "note": "趁热吃，底部焦脆"},
        {"id": "sh-r-yongshang", "name": "甬府（外滩店）", "lon": 121.4910, "lat": 31.2390, "price": 400,
         "cuisine": "宁波菜", "meal": ["dinner"], "dish": "黄鱼、红膏炝蟹", "note": "预算宽裕再考虑，需预约"},
        {"id": "sh-r-ajiang", "name": "阿娘面馆", "lon": 121.4720, "lat": 31.2240, "price": 45,
         "cuisine": "面食", "meal": ["lunch"], "dish": "黄鱼面、辣酱面", "note": "只做午市，卖完就收"},
        {"id": "sh-r-huoshao", "name": "大壶春（云南南路）", "lon": 121.4780, "lat": 31.2290, "price": 30,
         "cuisine": "小吃", "meal": ["breakfast", "lunch"], "dish": "生煎、小馄饨", "note": "全发酵生煎，老派做法"},
    ],
    "杭州": [
        {"id": "hz-r-louwaifor", "name": "楼外楼（孤山路）", "lon": 120.1430, "lat": 30.2530, "price": 180,
         "cuisine": "杭帮菜", "meal": ["lunch", "dinner"], "dish": "西湖醋鱼、东坡肉、叫花鸡", "note": "湖景位要早去"},
        {"id": "hz-r-zhizhuguan", "name": "知味观（湖滨总店）", "lon": 120.1610, "lat": 30.2570, "price": 70,
         "cuisine": "杭帮菜", "meal": ["breakfast", "lunch"], "dish": "片儿川、猫耳朵、小笼", "note": "早点比正餐更值"},
        {"id": "hz-r-xinchang", "name": "新白鹿（西湖银泰店）", "lon": 120.1630, "lat": 30.2530, "price": 80,
         "cuisine": "杭帮菜", "meal": ["lunch", "dinner"], "dish": "蛋黄鸡翅、糖醋排骨", "note": "性价比高，需取号"},
        {"id": "hz-r-longjing", "name": "龙井草堂", "lon": 120.1080, "lat": 30.2300, "price": 500,
         "cuisine": "私房菜", "meal": ["dinner"], "dish": "时令套餐", "note": "高端私房菜，需预约"},
        {"id": "hz-r-shengjian", "name": "高祖生煎（河坊街）", "lon": 120.1690, "lat": 30.2430, "price": 30,
         "cuisine": "小吃", "meal": ["breakfast", "lunch"], "dish": "生煎、葱包烩", "note": "边走边吃刚好"},
        {"id": "hz-r-pianerchuan", "name": "方老大面", "lon": 120.1700, "lat": 30.2490, "price": 40,
         "cuisine": "面食", "meal": ["lunch"], "dish": "片儿川、虾爆鳝面", "note": "本地人排队的面馆"},
    ],
    "成都": [
        {"id": "cd-r-shujiuxiang", "name": "蜀九香火锅（武侯祠店）", "lon": 104.0460, "lat": 30.6450, "price": 110,
         "cuisine": "火锅", "meal": ["dinner"], "dish": "牛油锅、毛肚、鹅肠", "note": "晚上排队久，可午市去"},
        {"id": "cd-r-chenmapo", "name": "陈麻婆豆腐（青羊店）", "lon": 104.0700, "lat": 30.6690, "price": 60,
         "cuisine": "川菜", "meal": ["lunch", "dinner"], "dish": "麻婆豆腐、回锅肉", "note": "老字号，麻味正"},
        {"id": "cd-r-zhongshuijiao", "name": "钟水饺（总店）", "lon": 104.0780, "lat": 30.6570, "price": 30,
         "cuisine": "小吃", "meal": ["breakfast", "lunch"], "dish": "红油水饺、甜水面", "note": "小吃拼一套"},
        {"id": "cd-r-longchaoshou", "name": "龙抄手（春熙路总店）", "lon": 104.0800, "lat": 30.6540, "price": 40,
         "cuisine": "小吃", "meal": ["breakfast", "lunch"], "dish": "红油抄手、担担面", "note": "一套小吃拼盘最省事"},
        {"id": "cd-r-dandan", "name": "老麻抄手（宽窄巷子）", "lon": 104.0550, "lat": 30.6660, "price": 35,
         "cuisine": "小吃", "meal": ["lunch"], "dish": "担担面、钵钵鸡", "note": "辣度可选"},
        {"id": "cd-r-yuxiang", "name": "马旺子·川小馆", "lon": 104.0840, "lat": 30.6510, "price": 100,
         "cuisine": "川菜", "meal": ["dinner"], "dish": "毛血旺、干烧臊子辽参", "note": "网红川菜馆，需预约"},
    ],
    "西安": [
        {"id": "xa-r-laosun", "name": "老孙家泡馍", "lon": 108.9480, "lat": 34.2640, "price": 50,
         "cuisine": "清真", "meal": ["lunch", "dinner"], "dish": "牛羊肉泡馍、凉皮", "note": "自己掰馍更入味"},
        {"id": "xa-r-zifeilu", "name": "子午路张记肉夹馍", "lon": 108.9440, "lat": 34.2380, "price": 20,
         "cuisine": "小吃", "meal": ["breakfast", "lunch"], "dish": "腊汁肉夹馍、凉皮", "note": "本地人早餐"},
        {"id": "xa-r-biangbiang", "name": "biangbiang 面（南院门）", "lon": 108.9460, "lat": 34.2580, "price": 25,
         "cuisine": "面食", "meal": ["lunch"], "dish": "油泼面、biangbiang 面", "note": "手工宽面，辣子香"},
        {"id": "xa-r-fanzhuang", "name": "西安饭庄（东大街）", "lon": 108.9560, "lat": 34.2590, "price": 110,
         "cuisine": "陕菜", "meal": ["lunch", "dinner"], "dish": "葫芦鸡、金线油塔", "note": "陕菜老字号"},
        {"id": "xa-r-hujia", "name": "胡辣汤（洒金桥）", "lon": 108.9400, "lat": 34.2670, "price": 15,
         "cuisine": "小吃", "meal": ["breakfast"], "dish": "肉丸胡辣汤、坨坨馍", "note": "早上 10 点前才有"},
    ],
    "广州": [
        {"id": "gz-r-zaocha", "name": "点都德（惠福东路）", "lon": 113.2500, "lat": 23.1210, "price": 70,
         "cuisine": "早茶", "meal": ["breakfast", "lunch"], "dish": "虾饺、凤爪、流沙包", "note": "早茶必点一盅两件"},
        {"id": "gz-r-bingsheng", "name": "炳胜品味（天河）", "lon": 113.3280, "lat": 23.1260, "price": 160,
         "cuisine": "粤菜", "meal": ["lunch", "dinner"], "dish": "烧鹅、脆皮叉烧", "note": "粤菜正餐，需订位"},
        {"id": "gz-r-shangxiajiu", "name": "陈添记鱼皮（宝华路）", "lon": 113.2420, "lat": 23.1160, "price": 30,
         "cuisine": "小吃", "meal": ["lunch"], "dish": "爽鱼皮、艇仔粥", "note": "只卖几样，很地道"},
        {"id": "gz-r-guangzhou", "name": "广州酒家（文昌南路）", "lon": 113.2400, "lat": 23.1140, "price": 100,
         "cuisine": "粤菜", "meal": ["breakfast", "lunch", "dinner"], "dish": "白切鸡、虾饺", "note": "老字号，早茶人多"},
        {"id": "gz-r-yinji", "name": "银记肠粉（文明路）", "lon": 113.2560, "lat": 23.1250, "price": 20,
         "cuisine": "小吃", "meal": ["breakfast"], "dish": "布拉肠粉、艇仔粥", "note": "早餐十分钟搞定"},
    ],
}

# 酒店：按 city + 档次给夜间均价（元/晚），用市中心点做示意坐标
HOTELS: Dict[str, Dict[str, dict]] = {
    "北京": {
        "economy": {"id": "bj-h-e", "name": "前门建国饭店·商务楼", "price": 320, "lon": 116.3920, "lat": 39.8970},
        "comfort": {"id": "bj-h-c", "name": "北京诺富特和平宾馆", "price": 620, "lon": 116.4100, "lat": 39.9130},
        "premium": {"id": "bj-h-p", "name": "王府半岛酒店", "price": 1600, "lon": 116.4140, "lat": 39.9150},
    },
    "上海": {
        "economy": {"id": "sh-h-e", "name": "静安寺亚朵酒店", "price": 420, "lon": 121.4460, "lat": 31.2240},
        "comfort": {"id": "sh-h-c", "name": "外滩华尔道夫·精选房", "price": 1100, "lon": 121.4890, "lat": 31.2380},
        "premium": {"id": "sh-h-p", "name": "上海浦东丽思卡尔顿", "price": 1900, "lon": 121.5040, "lat": 31.2380},
    },
    "杭州": {
        "economy": {"id": "hz-h-e", "name": "湖滨银泰全季酒店", "price": 300, "lon": 120.1620, "lat": 30.2540},
        "comfort": {"id": "hz-h-c", "name": "西湖国宾馆·湖景房", "price": 900, "lon": 120.1370, "lat": 30.2450},
        "premium": {"id": "hz-h-p", "name": "杭州安缦法云", "price": 3000, "lon": 120.1010, "lat": 30.2430},
    },
    "成都": {
        "economy": {"id": "cd-h-e", "name": "春熙路亚朵酒店", "price": 280, "lon": 104.0800, "lat": 30.6540},
        "comfort": {"id": "cd-h-c", "name": "太古里博舍", "price": 900, "lon": 104.0820, "lat": 30.6540},
        "premium": {"id": "cd-h-p", "name": "成都群光君悦酒店", "price": 1300, "lon": 104.0830, "lat": 30.6520},
    },
    "西安": {
        "economy": {"id": "xa-h-e", "name": "钟楼亚朵酒店", "price": 260, "lon": 108.9470, "lat": 34.2620},
        "comfort": {"id": "xa-h-c", "name": "西安索菲特人民大厦", "price": 600, "lon": 108.9560, "lat": 34.2650},
        "premium": {"id": "xa-h-p", "name": "西安W酒店", "price": 1200, "lon": 108.9730, "lat": 34.2170},
    },
    "广州": {
        "economy": {"id": "gz-h-e", "name": "北京路亚朵酒店", "price": 280, "lon": 113.2580, "lat": 23.1240},
        "comfort": {"id": "gz-h-c", "name": "广州白天鹅宾馆", "price": 800, "lon": 113.2390, "lat": 23.1080},
        "premium": {"id": "gz-h-p", "name": "广州四季酒店", "price": 1500, "lon": 113.3290, "lat": 23.1210},
    },
}

# 交通参考：市内打车单价 & 起租（国内中型城市平均）
TAXI_START = 13.0      # 起步价（元，含 3km）
TAXI_PER_KM = 2.6      # 每公里（元）
TRANSIT_PER_MOVE = 4.0 # 每段公共交通均价（元/人）

CITY_CENTER = {
    "北京": (116.3975, 39.9087),
    "上海": (121.4737, 31.2304),
    "杭州": (120.1551, 30.2741),
    "成都": (104.0668, 30.5728),
    "西安": (108.9402, 34.3416),
    "广州": (113.2644, 23.1291),
}


def city_list() -> List[str]:
    return list(SPOTS.keys())


def spot_index(city: str) -> Dict[str, dict]:
    return {s["id"]: s for s in SPOTS.get(city, [])}


def eatery_index(city: str) -> Dict[str, dict]:
    return {e["id"]: e for e in EATERIES.get(city, [])}


def hotel_for(city: str, tier: str) -> Optional[dict]:
    tiers = HOTELS.get(city) or {}
    return tiers.get(tier) or tiers.get("comfort")


def candidates_text(city: str) -> str:
    """给提示词用的候选清单（只给 id/名称/价格/标签，省 token）。"""
    city = city if city in SPOTS else "北京"
    spots = "；".join(
        "{i}:{n}({t}元,{h}h,{g})".format(
            i=s["id"], n=s["name"], t=s["ticket"], h=s["hours"], g="/".join(s["tags"][:2])
        )
        for s in SPOTS[city]
    )
    eats = "；".join(
        "{i}:{n}(人均{p}元,{c})".format(i=e["id"], n=e["name"], p=e["price"], c=e["cuisine"])
        for e in EATERIES[city]
    )
    return "景点候选（id:名称(门票,建议时长,标签)）：" + spots + "\n餐饮候选（id:名称(人均,菜系)）：" + eats


def all_cities_summary() -> List[dict]:
    out = []
    for city, spots in SPOTS.items():
        lon, lat = CITY_CENTER[city]
        out.append({"city": city, "spots": len(spots), "eateries": len(EATERIES.get(city, [])), "center": [lon, lat]})
    return out
