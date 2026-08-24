"""
Offline Local Spots & Poetry Knowledge Base for Lele AI Passport.
Allows zero-latency, offline browsing of all 16 itinerary spots.
"""

SPOTS = [
    {
        "spot": "白马寺",
        "city": "洛阳",
        "grade": "历史典故必知",
        "poem": "《题白马寺》· 贾岛",
        "verse": "白马驮经自宛延，空门从此度人天。",
        "celebrity": "汉明帝、摄摩腾竺法兰",
        "quiz": "‘白马驮经’四字口诀！",
        "index": 0,
        "total": 16
    },
    {
        "spot": "龙门石窟",
        "city": "洛阳",
        "grade": "初中七年级下册",
        "poem": "《春夜洛城闻笛》· 李白",
        "verse": "谁家玉笛暗飞声，散入春风满洛城。",
        "celebrity": "武则天、白居易",
        "quiz": "卢舍那大佛被称‘东方蒙娜丽莎’！",
        "index": 1,
        "total": 16
    },
    {
        "spot": "夫子庙 · 秦淮河",
        "city": "南京",
        "grade": "小学四年级必背",
        "poem": "《乌衣巷》· 刘禹锡",
        "verse": "旧时王谢堂前燕，飞入寻常百姓家。",
        "celebrity": "王导、谢安",
        "quiz": "王导谢安燕子飞入百姓家！",
        "index": 2,
        "total": 16
    },
    {
        "spot": "中华门瓮城",
        "city": "南京",
        "grade": "初高中拓展",
        "poem": "《桂枝香》· 王安石",
        "verse": "千里澄江似练，翠峰如簇。",
        "celebrity": "朱元璋、沈万三",
        "quiz": "三道瓮城关门捉贼瓮中捉鳖！",
        "index": 3,
        "total": 16
    },
    {
        "spot": "洛阳博物馆",
        "city": "洛阳",
        "grade": "初中七年级上册",
        "poem": "《江南逢李龟年》· 杜甫",
        "verse": "正是江南好风景，落花时节又逢君。",
        "celebrity": "杜甫、周公旦",
        "quiz": "寻宝找中国最早青铜酒杯华夏第一爵！",
        "index": 4,
        "total": 16
    },
    {
        "spot": "大雁塔",
        "city": "西安",
        "grade": "小学必背古诗",
        "poem": "《登科后》· 孟郊",
        "verse": "春风得意马蹄疾，一日看尽长安花。",
        "celebrity": "玄奘法师、白居易",
        "quiz": "唐僧玄奘取经17年建大雁塔！",
        "index": 5,
        "total": 16
    },
    {
        "spot": "大唐不夜城",
        "city": "西安",
        "grade": "初高中必背古诗",
        "poem": "《将进酒》· 李白",
        "verse": "人生得意须尽欢，莫使金樽空对月。",
        "celebrity": "李白、不倒翁姐姐",
        "quiz": "不夜城街头和李白对诗赢毛笔酥！",
        "index": 6,
        "total": 16
    },
    {
        "spot": "秦始皇兵马俑",
        "city": "西安",
        "grade": "初中古典名篇",
        "poem": "《秦王扫六合》· 李白",
        "verse": "秦王扫六合，虎视何雄哉！",
        "celebrity": "秦始皇嬴政",
        "quiz": "地下八千勇士千人千面原本有颜色！",
        "index": 7,
        "total": 16
    },
    {
        "spot": "西安城墙",
        "city": "西安",
        "grade": "历史建筑奇迹",
        "poem": "《关中八景》明代城垣",
        "verse": "十三里长明城在，古今凭眺倚栏看。",
        "celebrity": "朱元璋、明朝工匠",
        "quiz": "糯米熬浓粥灌强力胶城墙600年不倒！",
        "index": 8,
        "total": 16
    },
    {
        "spot": "华山西峰索道",
        "city": "华山",
        "grade": "小学一年级语文",
        "poem": "《咏华山》· 寇准",
        "verse": "举头红日近，回首白云低。",
        "celebrity": "神童寇准、沉香",
        "quiz": "沉香劈山救母神石一斧劈两半！",
        "index": 9,
        "total": 16
    },
    {
        "spot": "函谷关 & 潼关",
        "city": "三门峡",
        "grade": "初中八年级必背",
        "poem": "《潼关怀古》· 张养浩",
        "verse": "峰峦如聚，波涛如怒，山河表里潼关路。",
        "celebrity": "老子、尹喜",
        "quiz": "老子骑青牛紫气东来著道德经！",
        "index": 10,
        "total": 16
    },
    {
        "spot": "陕州地坑院",
        "city": "三门峡",
        "grade": "民俗民居奇观",
        "poem": "民俗谚语",
        "verse": "见树不见村，进村不见人。",
        "celebrity": "古代劳动人民",
        "quiz": "地下四合院冬暖夏凉暴雨一秒渗干！",
        "index": 11,
        "total": 16
    },
    {
        "spot": "三门峡大坝",
        "city": "三门峡",
        "grade": "水利与神话精神",
        "poem": "《公无渡河》· 李白",
        "verse": "黄河西来决昆仑，咆哮万里触龙门。",
        "celebrity": "大禹",
        "quiz": "大禹神斧劈三门中流砥柱立沧海！",
        "index": 12,
        "total": 16
    },
    {
        "spot": "清明上河园",
        "city": "开封",
        "grade": "小学五年级必背",
        "poem": "《题临安邸》· 林升",
        "verse": "暖风熏得游人醉，直把杭州作汴州。",
        "celebrity": "张择端、宋徽宗",
        "quiz": "自驾从杭州到开封实现古诗同款！",
        "index": 13,
        "total": 16
    },
    {
        "spot": "鼓楼夜市",
        "city": "开封",
        "grade": "宋代饮食文化",
        "poem": "《东京梦华录》",
        "verse": "夜市直至三更尽，才五更又复开张。",
        "celebrity": "宋代开封名厨",
        "quiz": "轻轻提慢慢移先开窗后喝汤！",
        "index": 14,
        "total": 16
    },
    {
        "spot": "龙亭公园",
        "city": "开封",
        "grade": "小学五年级必背",
        "poem": "《示儿》· 陆游",
        "verse": "王师北定中原日，家祭无忘告乃翁。",
        "celebrity": "包拯、杨家将",
        "quiz": "潘家湖浑杨家湖清湖水辨忠奸！",
        "index": 15,
        "total": 16
    }
]
