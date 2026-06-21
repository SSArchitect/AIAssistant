const STORAGE_KEY = 'weight-loss-checkin-v1';

const PLAN_BLUEPRINTS = [
    {
        phase: '启动周',
        title: '把开局先稳住',
        walk: 25,
        foodTitle: '饮料全部换成无糖',
        foodNote: '早餐先吃蛋白质，主食先定一拳头。',
        recoveryTitle: '今晚开始侧卧睡',
        recoveryNote: '下午两点后少咖啡，别用安眠药硬压。',
        promptTitle: '先做减法',
        promptNote: '把奶茶、可乐和高糖零食挪开，今天最重要。',
        challenge: '把含糖饮料和顺手零食移出手边'
    },
    {
        phase: '启动周',
        title: '早餐先固定住',
        walk: 25,
        foodTitle: '早餐别空着',
        foodNote: '鸡蛋、无糖酸奶、豆浆任选两样搭起来。',
        recoveryTitle: '早上晒 10 分钟太阳',
        recoveryNote: '先把起床节奏拉回来，别一醒来就刷手机。',
        promptTitle: '今天别靠意志力',
        promptNote: '提前想好早餐，执行会容易很多。',
        challenge: '今天三餐都要出现蛋白质'
    },
    {
        phase: '启动周',
        title: '晚饭后走起来',
        walk: 30,
        foodTitle: '午晚餐先吃菜和蛋白质',
        foodNote: '吃饭速度慢一点，至少吃 15 分钟。',
        recoveryTitle: '睡前 30 分钟降速',
        recoveryNote: '不看刺激内容，给身体一个收尾信号。',
        promptTitle: '别等状态好了再动',
        promptNote: '今天走完再说，不用等完全有劲。',
        challenge: '晚饭后散步 30 分钟，可拆成 15 + 15'
    },
    {
        phase: '启动周',
        title: '第一次力量训练',
        walk: 30,
        strength: true,
        foodTitle: '外卖也要控结构',
        foodNote: '先保住一掌心蛋白质和半盘菜。',
        recoveryTitle: '训练后别报复性进食',
        recoveryNote: '练完可以正常吃饭，不用奖励自己。',
        promptTitle: '轻一点也算练',
        promptNote: '深蹲、靠墙俯卧撑、臀桥各两组就够了。',
        challenge: '完成 15 到 20 分钟基础力量训练'
    },
    {
        phase: '启动周',
        title: '把夜宵截断',
        walk: 30,
        foodTitle: '晚上真饿就吃轻加餐',
        foodNote: '鸡蛋、无糖酸奶、豆浆可以，别开第二顿。',
        recoveryTitle: '困就早点睡',
        recoveryNote: '别用刷手机拖到更晚，睡意来了就躺平。',
        promptTitle: '低成本赢一把',
        promptNote: '今天只要别夜宵，已经很关键。',
        challenge: '今天不碰夜宵，也不边看边吃'
    },
    {
        phase: '启动周',
        title: '外卖减油减糖',
        walk: 30,
        foodTitle: '点单时主动做选择',
        foodNote: '少饭、多菜、加蛋白，不配含糖饮料。',
        recoveryTitle: '今天加一次拉伸',
        recoveryNote: '走路后拉小腿和臀部，给关节减压。',
        promptTitle: '别追求完美点单',
        promptNote: '能比以前更好一点，就在往前。',
        challenge: '今天至少有一餐是你主动优化过的外卖'
    },
    {
        phase: '启动周',
        title: '第一周复盘',
        walk: 35,
        foodTitle: '回看本周最容易失守的餐',
        foodNote: '不是批评自己，是找出破口。',
        recoveryTitle: '今天早点睡 30 分钟',
        recoveryNote: '先保住恢复，别熬到情绪上来。',
        promptTitle: '保住连续性',
        promptNote: '这一周不求完美，只求别断。',
        challenge: '写下这周最容易破功的一个场景和一个应对办法'
    },
    {
        phase: '节奏周',
        title: '第二周开始提速',
        walk: 35,
        foodTitle: '主食继续定量',
        foodNote: '别断主食，但也别无限续饭。',
        recoveryTitle: '醒来就见光',
        recoveryNote: '起床后尽快接触自然光，晚上会更容易困。',
        promptTitle: '节奏比猛更重要',
        promptNote: '把今天走完，比想着明天加倍更有用。',
        challenge: '今天至少走满 35 分钟'
    },
    {
        phase: '节奏周',
        title: '午后不再靠咖啡硬顶',
        walk: 35,
        foodTitle: '下午嘴馋准备轻加餐',
        foodNote: '水果或无糖酸奶都比奶茶稳很多。',
        recoveryTitle: '下午两点后停咖啡',
        recoveryNote: '把困意留给晚上，睡眠会慢慢回来。',
        promptTitle: '精力不是靠顶出来的',
        promptNote: '你现在更需要恢复，而不是强撑。',
        challenge: '下午两点后不喝咖啡和浓茶'
    },
    {
        phase: '节奏周',
        title: '第二次力量训练',
        walk: 35,
        strength: true,
        foodTitle: '练前后都正常吃',
        foodNote: '不是奖励餐，也不是硬饿着。',
        recoveryTitle: '训练动作慢一点',
        recoveryNote: '关节舒服最重要，先稳住动作质量。',
        promptTitle: '不需要一次练很猛',
        promptNote: '完成就赢，今天先做基础版。',
        challenge: '今天完成第二次力量训练'
    },
    {
        phase: '节奏周',
        title: '吃饭顺序再优化',
        walk: 35,
        foodTitle: '每餐先吃蛋白质',
        foodNote: '蛋白质先到位，饱腹感会明显好很多。',
        recoveryTitle: '晚饭后别立刻瘫下',
        recoveryNote: '先站一站，再轻松走一段。',
        promptTitle: '今天只改一个细节',
        promptNote: '顺序对了，后面就容易了。',
        challenge: '三餐都先吃蛋白质，再吃主食'
    },
    {
        phase: '节奏周',
        title: '蔬菜量抬起来',
        walk: 40,
        foodTitle: '午晚餐都做到半盘菜',
        foodNote: '蔬菜不一定清淡，但要明显看得见。',
        recoveryTitle: '睡前让大脑降速',
        recoveryNote: '可以听点轻的东西，别继续刷工作信息。',
        promptTitle: '吃饱比饿住更重要',
        promptNote: '菜量够了，才更容易顶住晚上嘴馋。',
        challenge: '今天至少两餐做到半盘蔬菜'
    },
    {
        phase: '节奏周',
        title: '晚餐留到八分饱',
        walk: 40,
        foodTitle: '吃到不撑为止',
        foodNote: '不是饿，是吃完不想再去找别的。',
        recoveryTitle: '今天早点关灯',
        recoveryNote: '让身体知道夜里是用来恢复的。',
        promptTitle: '饱和撑不是一回事',
        promptNote: '慢一点，给大脑时间接收到信号。',
        challenge: '今天晚餐不吃撑，也不补夜宵'
    },
    {
        phase: '节奏周',
        title: '第二周复盘',
        walk: 40,
        foodTitle: '看一下哪一顿最容易超标',
        foodNote: '通常不是因为饿，而是因为累和烦。',
        recoveryTitle: '做一次 10 分钟慢呼吸',
        recoveryNote: '把压力先降一格，执行才会更稳。',
        promptTitle: '看到自己在变稳',
        promptNote: '你已经不是第一天的状态了。',
        challenge: '写下这一周做得最稳的两个动作'
    },
    {
        phase: '推进周',
        title: '第三周开始稳步推进',
        walk: 40,
        foodTitle: '早餐和午餐继续守结构',
        foodNote: '白天吃稳，晚上才不会报复性进食。',
        recoveryTitle: '白天久坐就起身走一圈',
        recoveryNote: '别让整天都陷在一个姿势里。',
        promptTitle: '先把今天过好',
        promptNote: '不用想着后面 15 天，只盯今天。',
        challenge: '今天累计步行 40 分钟'
    },
    {
        phase: '推进周',
        title: '高压时先散步再决定',
        walk: 40,
        foodTitle: '情绪上来时先喝水',
        foodNote: '给自己 10 分钟缓冲，别立刻点高热量外卖。',
        recoveryTitle: '安排一个无打扰空档',
        recoveryNote: '压力很大的时候，空档比鸡血更有用。',
        promptTitle: '别把焦虑全吃下去',
        promptNote: '先动一动，脑子会清一点。',
        challenge: '焦虑来的时候先走 10 分钟，再决定吃什么'
    },
    {
        phase: '推进周',
        title: '第三次力量训练',
        walk: 40,
        strength: true,
        foodTitle: '练完补正常正餐',
        foodNote: '蛋白质到位，主食正常量，不用报复性吃。',
        recoveryTitle: '训练后洗澡放松',
        recoveryNote: '让身体把紧绷慢慢卸下来。',
        promptTitle: '保住肌肉，减得更稳',
        promptNote: '力量训练是给你底盘，不是为了折腾。',
        challenge: '完成第三次力量训练'
    },
    {
        phase: '推进周',
        title: '零食换轨',
        walk: 40,
        foodTitle: '把高热量零食换成轻一点的',
        foodNote: '水果、无糖酸奶、鸡蛋都比顺手拿饼干稳。',
        recoveryTitle: '睡前不补工作内容',
        recoveryNote: '晚上不要再让脑子兴奋起来。',
        promptTitle: '环境比意志力重要',
        promptNote: '别把诱惑放得太近。',
        challenge: '今天所有加餐只从水果、鸡蛋、无糖酸奶里选'
    },
    {
        phase: '推进周',
        title: '停止边看边吃',
        walk: 45,
        foodTitle: '吃饭就只吃饭',
        foodNote: '不刷视频、不看剧，食量会自然收回来。',
        recoveryTitle: '走路后做 5 分钟拉伸',
        recoveryNote: '让小腿和髋部松下来，第二天更轻松。',
        promptTitle: '专心吃，身体更知道够了',
        promptNote: '看似小动作，其实很顶用。',
        challenge: '今天不边看边吃'
    },
    {
        phase: '推进周',
        title: '给高压日一个保底版',
        walk: 30,
        foodTitle: '今天只保住基本线',
        foodNote: '饮料无糖、别暴食、晚饭后走一段就够。',
        recoveryTitle: '允许自己只做保底',
        recoveryNote: '状态差时，持续比完美更关键。',
        promptTitle: '保底日不是失败',
        promptNote: '能顶住不崩，就已经很强。',
        challenge: '今天只做最低完成线也算数'
    },
    {
        phase: '推进周',
        title: '第三周复盘',
        walk: 45,
        foodTitle: '回看前三周最有效的动作',
        foodNote: '留下对你最有用的，不必贪多。',
        recoveryTitle: '给自己一个放松夜晚',
        recoveryNote: '早点收工，别用食物安慰自己。',
        promptTitle: '你已经在建立新节奏',
        promptNote: '把它看成养身体，不是惩罚自己。',
        challenge: '写下最适合你的三个习惯'
    },
    {
        phase: '收口周',
        title: '第四周开始收口',
        walk: 45,
        foodTitle: '继续把白天吃稳',
        foodNote: '白天规律，晚上会轻松很多。',
        recoveryTitle: '起床时间继续固定',
        recoveryNote: '假期和周末也尽量别睡崩。',
        promptTitle: '最后一周别松太大',
        promptNote: '不是冲刺，是把新节奏坐实。',
        challenge: '今天累计走满 45 分钟'
    },
    {
        phase: '收口周',
        title: '第四次力量训练',
        walk: 45,
        strength: true,
        foodTitle: '训练日也不乱吃',
        foodNote: '正常吃，别因为练了就奖赏自己。',
        recoveryTitle: '动作慢，呼吸稳',
        recoveryNote: '把关节照顾好，比多做几下更重要。',
        promptTitle: '你是在给以后打底',
        promptNote: '减脂期保住体能，非常值。',
        challenge: '今天完成第四次力量训练'
    },
    {
        phase: '收口周',
        title: '周末也不暴食',
        walk: 45,
        foodTitle: '聚餐也别失控',
        foodNote: '先吃蛋白质和菜，主食和甜品适量。',
        recoveryTitle: '不要因为周末就熬太晚',
        recoveryNote: '睡眠乱掉，食欲也会跟着乱。',
        promptTitle: '享受不等于放飞',
        promptNote: '吃喜欢的可以，但别失控。',
        challenge: '今天就算外出也不暴食'
    },
    {
        phase: '收口周',
        title: '睡前把手机放远一点',
        walk: 45,
        foodTitle: '晚上别再加一顿',
        foodNote: '肚子不饿的时候，就别让情绪来点单。',
        recoveryTitle: '睡前 30 分钟不刷刺激内容',
        recoveryNote: '让大脑真正收尾，睡眠会更实在。',
        promptTitle: '困了就去睡',
        promptNote: '不用把清醒时间硬拉长。',
        challenge: '今天睡前 30 分钟不刷刺激内容'
    },
    {
        phase: '收口周',
        title: '第五次力量训练',
        walk: 45,
        strength: true,
        foodTitle: '继续守住蛋白质',
        foodNote: '每餐有蛋白质，掉秤会更稳。',
        recoveryTitle: '训练后别瘫一晚上',
        recoveryNote: '拉伸 5 分钟，让身体慢慢回落。',
        promptTitle: '第五次了，已经不是凑热闹',
        promptNote: '你在做成一件事，而不是试试。',
        challenge: '今天完成第五次力量训练'
    },
    {
        phase: '收口周',
        title: '减少重口外卖',
        walk: 45,
        foodTitle: '主动把外卖点轻一点',
        foodNote: '酱汁少一点、主食减一点、蔬菜多一点。',
        recoveryTitle: '下午安排一个无屏幕散步',
        recoveryNote: '不带任务地走几分钟，脑子会轻很多。',
        promptTitle: '主动选择就是在掌控',
        promptNote: '不必每顿完美，但别交给惯性。',
        challenge: '今天至少有一餐明显比以前更清爽'
    },
    {
        phase: '收口周',
        title: '给自己一个非食物奖励',
        walk: 45,
        foodTitle: '今天继续三餐稳定',
        foodNote: '别因为奖励心态又吃回去。',
        recoveryTitle: '晚上做点真正放松的事',
        recoveryNote: '散步、看书、洗澡都可以。',
        promptTitle: '奖励不是吃回来',
        promptNote: '你可以用别的方式肯定自己。',
        challenge: '今天给自己一个非食物奖励'
    },
    {
        phase: '收口周',
        title: '第六次力量训练',
        walk: 45,
        strength: true,
        foodTitle: '维持前面已经有效的结构',
        foodNote: '这一天不需要创新，只要继续。',
        recoveryTitle: '训练后早点休息',
        recoveryNote: '最后两天更要把恢复接住。',
        promptTitle: '稳定，就是很强',
        promptNote: '做到第六次，你已经在改身体了。',
        challenge: '今天完成第六次力量训练'
    },
    {
        phase: '收口周',
        title: '30天收官复盘',
        walk: 50,
        foodTitle: '今天照常吃，不庆祝性暴食',
        foodNote: '把最后一天过稳，比乱吃更值。',
        recoveryTitle: '回顾这个月最有效的动作',
        recoveryNote: '你不是回到原点，而是要接着往下走。',
        promptTitle: '把计划续下去',
        promptNote: '留下 3 个你最想继续的习惯，下一阶段继续。',
        challenge: '写下接下来 30 天你最想继续保留的三个动作'
    }
];

const defaultProfile = {
    startDate: todayISO(),
    startWeight: 120,
    goalWeight: 115,
    walkGoal: 35
};

const state = loadState();

const elements = {
    startDate: document.getElementById('start-date'),
    startWeight: document.getElementById('start-weight'),
    goalWeight: document.getElementById('goal-weight'),
    walkGoal: document.getElementById('walk-goal'),
    saveProfile: document.getElementById('save-profile'),
    exportData: document.getElementById('export-data'),
    importDataTrigger: document.getElementById('import-data-trigger'),
    importDataFile: document.getElementById('import-data-file'),
    resetPlan: document.getElementById('reset-plan'),
    jumpToday: document.getElementById('jump-today'),
    statCurrentDay: document.getElementById('stat-current-day'),
    statDayNote: document.getElementById('stat-day-note'),
    statCompletedDays: document.getElementById('stat-completed-days'),
    statStreak: document.getElementById('stat-streak'),
    statWeightChange: document.getElementById('stat-weight-change'),
    statLatestWeight: document.getElementById('stat-latest-weight'),
    statSleepAverage: document.getElementById('stat-sleep-average'),
    statSleepNote: document.getElementById('stat-sleep-note'),
    chartCaption: document.getElementById('chart-caption'),
    weightChart: document.getElementById('weight-chart'),
    selectedDayLabel: document.getElementById('selected-day-label'),
    selectedDayTitle: document.getElementById('selected-day-title'),
    selectedDayPhase: document.getElementById('selected-day-phase'),
    selectedDayDate: document.getElementById('selected-day-date'),
    selectedDayWalk: document.getElementById('selected-day-walk'),
    selectedDayWalkNote: document.getElementById('selected-day-walk-note'),
    selectedDayFood: document.getElementById('selected-day-food'),
    selectedDayFoodNote: document.getElementById('selected-day-food-note'),
    selectedDayRecovery: document.getElementById('selected-day-recovery'),
    selectedDayRecoveryNote: document.getElementById('selected-day-recovery-note'),
    selectedDayPrompt: document.getElementById('selected-day-prompt'),
    selectedDayPromptNote: document.getElementById('selected-day-prompt-note'),
    taskList: document.getElementById('task-list'),
    toggleDone: document.getElementById('toggle-done'),
    logWeight: document.getElementById('log-weight'),
    logSleep: document.getElementById('log-sleep'),
    logWalk: document.getElementById('log-walk'),
    logEnergy: document.getElementById('log-energy'),
    logNote: document.getElementById('log-note'),
    planGrid: document.getElementById('plan-grid')
};

init();

function init() {
    hydrateProfileInputs();
    bindEvents();
    renderAll();
}

function bindEvents() {
    elements.saveProfile.addEventListener('click', saveProfile);
    elements.exportData.addEventListener('click', exportData);
    elements.importDataTrigger.addEventListener('click', () => elements.importDataFile.click());
    elements.importDataFile.addEventListener('change', importData);
    elements.resetPlan.addEventListener('click', resetPlan);
    elements.jumpToday.addEventListener('click', () => {
        state.selectedDay = getCurrentDayIndex();
        renderAll();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    elements.toggleDone.addEventListener('click', toggleDoneForSelectedDay);

    [
        ['weight', elements.logWeight],
        ['sleepHours', elements.logSleep],
        ['walkMinutes', elements.logWalk],
        ['energy', elements.logEnergy],
        ['note', elements.logNote]
    ].forEach(([field, node]) => {
        node.addEventListener('input', (event) => updateSelectedLogField(field, event.target.value));
    });
}

function saveProfile() {
    const startWeight = clampNumber(parseFloat(elements.startWeight.value), 40, 300, defaultProfile.startWeight);
    const goalWeight = clampNumber(parseFloat(elements.goalWeight.value), 40, 300, Math.max(40, startWeight - 5));
    const walkGoal = clampNumber(parseFloat(elements.walkGoal.value), 15, 120, defaultProfile.walkGoal);

    state.profile.startDate = elements.startDate.value || todayISO();
    state.profile.startWeight = startWeight;
    state.profile.goalWeight = goalWeight;
    state.profile.walkGoal = walkGoal;

    if (!state.selectedDay) {
        state.selectedDay = getCurrentDayIndex();
    }

    saveState();
    renderAll();
    showToast('计划已保存');
}

function exportData() {
    const blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `weight-loss-plan-${todayISO()}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast('数据已导出');
}

function importData(event) {
    const [file] = event.target.files || [];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
        try {
            const imported = JSON.parse(String(reader.result));
            const normalized = normalizeState(imported);
            localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
            Object.assign(state, normalized);
            renderAll();
            showToast('数据已导入');
        } catch (error) {
            showToast('导入失败，请确认文件格式');
        } finally {
            elements.importDataFile.value = '';
        }
    };
    reader.readAsText(file);
}

function resetPlan() {
    const confirmed = window.confirm('这会清空当前浏览器里的 30 天打卡数据，确定重新开始吗？');
    if (!confirmed) return;

    const fresh = createDefaultState();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(fresh));
    Object.assign(state, fresh);
    renderAll();
    showToast('已经重新开始');
}

function toggleDoneForSelectedDay() {
    const log = getSelectedLog();
    log.completed = !log.completed;
    log.completedAt = log.completed ? new Date().toISOString() : '';
    saveState();
    renderAll();
}

function updateSelectedLogField(field, value) {
    const log = getSelectedLog();
    log[field] = value;
    saveState();
    renderOverview();
    renderPlanGrid();
}

function hydrateProfileInputs() {
    elements.startDate.value = state.profile.startDate;
    elements.startWeight.value = state.profile.startWeight;
    elements.goalWeight.value = state.profile.goalWeight;
    elements.walkGoal.value = state.profile.walkGoal;
}

function renderAll() {
    hydrateProfileInputs();
    renderOverview();
    renderSelectedDay();
    renderPlanGrid();
}

function renderOverview() {
    const currentDayIndex = getCurrentDayIndex();
    const completedDays = PLAN_BLUEPRINTS.filter((_, index) => state.logs[String(index + 1)]?.completed).length;
    const streak = calculateCurrentStreak();
    const latestWeightEntry = getLatestNumericEntry('weight');
    const startWeight = Number(state.profile.startWeight);
    const weightChange = latestWeightEntry ? latestWeightEntry.value - startWeight : 0;
    const avgSleep = averageLastSevenDays('sleepHours');

    elements.statCurrentDay.textContent = `第 ${currentDayIndex} 天`;
    elements.statDayNote.textContent = getDayNote(currentDayIndex);
    elements.statCompletedDays.textContent = `${completedDays} / 30`;
    elements.statStreak.textContent = `连续打卡 ${streak} 天`;
    elements.statWeightChange.textContent = latestWeightEntry ? formatWeightDelta(weightChange) : '0.0 kg';
    elements.statLatestWeight.textContent = latestWeightEntry
        ? `最近记录 ${latestWeightEntry.value.toFixed(1)} kg`
        : '还没有记录今日体重';
    elements.statSleepAverage.textContent = `${avgSleep.toFixed(1)} 小时`;
    elements.statSleepNote.textContent = avgSleep > 0
        ? avgSleep >= 7 ? '最近睡眠在慢慢回正' : '再把起床时间和晚间节奏稳一点'
        : '把起床时间固定下来';

    renderWeightChart();
}

function renderSelectedDay() {
    const day = getSelectedDay();
    const log = getSelectedLog();
    const tasks = buildTasks(day);
    const cardDate = getDateForDay(day.index);

    elements.selectedDayLabel.textContent = `DAY ${day.index}`;
    elements.selectedDayTitle.textContent = day.title;
    elements.selectedDayPhase.textContent = day.phase;
    elements.selectedDayDate.textContent = cardDate;
    elements.selectedDayWalk.textContent = `${day.walk} 分钟`;
    elements.selectedDayWalkNote.textContent = day.strength
        ? '今天有力量训练，步行可以拆开走。'
        : '饭后走最好，拆成两段也可以。';
    elements.selectedDayFood.textContent = day.foodTitle;
    elements.selectedDayFoodNote.textContent = day.foodNote;
    elements.selectedDayRecovery.textContent = day.recoveryTitle;
    elements.selectedDayRecoveryNote.textContent = day.recoveryNote;
    elements.selectedDayPrompt.textContent = day.promptTitle;
    elements.selectedDayPromptNote.textContent = day.promptNote;
    elements.toggleDone.textContent = log.completed ? '取消今日完成' : '标记今天完成';

    elements.taskList.innerHTML = tasks.map((task) => {
        const checked = Boolean(log.tasks?.[task.id]);
        return `
            <div class="task-item ${checked ? 'done' : ''}">
                <input type="checkbox" id="task-${day.index}-${task.id}" data-task-id="${task.id}" ${checked ? 'checked' : ''}>
                <label for="task-${day.index}-${task.id}">${escapeHtml(task.label)}</label>
            </div>
        `;
    }).join('');

    elements.taskList.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
        checkbox.addEventListener('change', (event) => {
            const taskId = event.target.dataset.taskId;
            const selectedLog = getSelectedLog();
            selectedLog.tasks[taskId] = event.target.checked;
            saveState();
            renderSelectedDay();
            renderOverview();
            renderPlanGrid();
        });
    });

    elements.logWeight.value = log.weight || '';
    elements.logSleep.value = log.sleepHours || '';
    elements.logWalk.value = log.walkMinutes || '';
    elements.logEnergy.value = log.energy || '';
    elements.logNote.value = log.note || '';
}

function renderPlanGrid() {
    const currentDayIndex = getCurrentDayIndex();
    const cards = PLAN_BLUEPRINTS.map((plan, rawIndex) => {
        const index = rawIndex + 1;
        const log = state.logs[String(index)] || createEmptyLog();
        const status = log.completed ? '已完成' : index === currentDayIndex ? '今天' : index < currentDayIndex ? '待补卡' : '待开始';
        const classes = [
            'plan-day-card',
            index === state.selectedDay ? 'selected' : '',
            log.completed ? 'completed' : '',
            index === currentDayIndex ? 'today' : '',
            index > currentDayIndex ? 'future' : ''
        ].filter(Boolean).join(' ');

        return `
            <button class="${classes}" type="button" data-day-index="${index}">
                <div class="plan-day-top">
                    <span class="day-number">${index}</span>
                    <span class="day-status">${status}</span>
                </div>
                <h3>${escapeHtml(plan.title)}</h3>
                <p>${escapeHtml(plan.challenge)}</p>
                <div class="plan-meta">
                    <span class="meta-pill">${plan.walk} 分钟步行</span>
                    <span class="meta-pill">${plan.phase}</span>
                    ${plan.strength ? '<span class="meta-pill">力量训练</span>' : ''}
                    <span class="meta-pill">${escapeHtml(getDateForDay(index))}</span>
                </div>
            </button>
        `;
    }).join('');

    elements.planGrid.innerHTML = cards;
    elements.planGrid.querySelectorAll('[data-day-index]').forEach((button) => {
        button.addEventListener('click', () => {
            state.selectedDay = Number(button.dataset.dayIndex);
            saveState();
            renderSelectedDay();
            renderPlanGrid();
            window.scrollTo({ top: document.querySelector('.panel:nth-of-type(2)').offsetTop - 16, behavior: 'smooth' });
        });
    });
}

function renderWeightChart() {
    const points = getLoggedWeights();

    if (points.length === 0) {
        elements.weightChart.innerHTML = `
            <rect x="0" y="0" width="420" height="180" rx="22" fill="rgba(255,255,255,0.72)"></rect>
            <text x="210" y="92" text-anchor="middle" fill="#8a7a62" font-size="14">开始记录体重后，这里会出现趋势图</text>
        `;
        elements.chartCaption.textContent = '先记录几天体重，趋势会比单天数字更有意义。';
        return;
    }

    const values = points.map((item) => item.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(max - min, 1);
    const chartWidth = 420;
    const chartHeight = 180;
    const padding = 20;
    const stepX = points.length === 1 ? 0 : (chartWidth - padding * 2) / (points.length - 1);
    const svgPoints = points.map((point, index) => {
        const x = padding + stepX * index;
        const y = chartHeight - padding - ((point.value - min) / range) * (chartHeight - padding * 2);
        return { x, y, value: point.value, index: point.index };
    });
    const polyline = svgPoints.map((point) => `${point.x},${point.y}`).join(' ');
    const area = `${padding},${chartHeight - padding} ${polyline} ${svgPoints[svgPoints.length - 1].x},${chartHeight - padding}`;
    const latest = svgPoints[svgPoints.length - 1];

    elements.weightChart.innerHTML = `
        <defs>
            <linearGradient id="weight-area" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stop-color="rgba(182,96,61,0.28)"></stop>
                <stop offset="100%" stop-color="rgba(182,96,61,0.02)"></stop>
            </linearGradient>
        </defs>
        <rect x="0" y="0" width="420" height="180" rx="22" fill="rgba(255,255,255,0.42)"></rect>
        <line x1="${padding}" y1="${chartHeight - padding}" x2="${chartWidth - padding}" y2="${chartHeight - padding}" stroke="rgba(71,57,38,0.12)" stroke-width="1"></line>
        <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${chartHeight - padding}" stroke="rgba(71,57,38,0.12)" stroke-width="1"></line>
        <polygon points="${area}" fill="url(#weight-area)"></polygon>
        <polyline points="${polyline}" fill="none" stroke="#b6603d" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"></polyline>
        ${svgPoints.map((point) => `
            <circle cx="${point.x}" cy="${point.y}" r="${point === latest ? 5.5 : 3.8}" fill="${point === latest ? '#276b69' : '#b6603d'}"></circle>
        `).join('')}
        <text x="${latest.x}" y="${Math.max(latest.y - 14, 16)}" text-anchor="middle" fill="#276b69" font-size="13">${latest.value.toFixed(1)} kg</text>
    `;

    const delta = points[points.length - 1].value - Number(state.profile.startWeight);
    elements.chartCaption.textContent = delta < 0
        ? `最近一次记录比起点轻了 ${Math.abs(delta).toFixed(1)} kg，继续按周看趋势就好。`
        : '体重有波动很正常，先把吃饭、走路和睡眠做稳。';
}

function getSelectedDay() {
    const index = clampNumber(state.selectedDay, 1, 30, getCurrentDayIndex());
    const plan = PLAN_BLUEPRINTS[index - 1];
    return { ...plan, index };
}

function getSelectedLog() {
    const key = String(getSelectedDay().index);
    if (!state.logs[key]) {
        state.logs[key] = createEmptyLog();
    }
    if (!state.logs[key].tasks) {
        state.logs[key].tasks = {};
    }
    return state.logs[key];
}

function buildTasks(day) {
    const tasks = [
        { id: 'sugarFree', label: '今天饮料全部无糖' },
        { id: 'protein', label: '三餐都出现蛋白质' },
        { id: 'walk', label: `完成 ${day.walk} 分钟步行` },
        { id: 'stressReset', label: '留出 10 分钟减压或散步' },
        { id: 'sleepGuard', label: '下午两点后不喝咖啡，今晚尽量侧卧' },
        { id: 'challenge', label: day.challenge }
    ];

    if (day.strength) {
        tasks.splice(3, 0, { id: 'strength', label: '完成 15 到 20 分钟基础力量训练' });
    }

    return tasks;
}

function getCurrentDayIndex() {
    const start = parseDateOnly(state.profile.startDate || todayISO());
    const today = parseDateOnly(todayISO());
    const diffDays = Math.floor((today - start) / 86400000) + 1;
    if (diffDays < 1) return 1;
    if (diffDays > 30) return 30;
    return diffDays;
}

function getDayNote(currentDayIndex) {
    const start = parseDateOnly(state.profile.startDate || todayISO());
    const today = parseDateOnly(todayISO());
    const rawDiff = Math.floor((today - start) / 86400000) + 1;

    if (rawDiff < 1) {
        return `计划将于 ${formatDate(start)} 开始`;
    }

    if (rawDiff > 30) {
        return '30 天计划已跑完，可以直接续下一轮';
    }

    return `距离收官还有 ${30 - currentDayIndex} 天`;
}

function getDateForDay(dayIndex) {
    const start = parseDateOnly(state.profile.startDate || todayISO());
    const date = new Date(start);
    date.setDate(start.getDate() + dayIndex - 1);
    return formatDate(date);
}

function averageLastSevenDays(field) {
    const numbers = Object.entries(state.logs)
        .map(([dayIndex, log]) => ({ dayIndex: Number(dayIndex), value: Number(log[field]) }))
        .filter((item) => Number.isFinite(item.value) && item.value > 0)
        .sort((a, b) => a.dayIndex - b.dayIndex)
        .slice(-7);

    if (numbers.length === 0) return 0;
    return numbers.reduce((sum, item) => sum + item.value, 0) / numbers.length;
}

function getLatestNumericEntry(field) {
    const entries = Object.entries(state.logs)
        .map(([dayIndex, log]) => ({ dayIndex: Number(dayIndex), value: Number(log[field]) }))
        .filter((item) => Number.isFinite(item.value) && item.value > 0)
        .sort((a, b) => a.dayIndex - b.dayIndex);

    return entries.length ? { index: entries[entries.length - 1].dayIndex, value: entries[entries.length - 1].value } : null;
}

function getLoggedWeights() {
    return Object.entries(state.logs)
        .map(([dayIndex, log]) => ({ index: Number(dayIndex), value: Number(log.weight) }))
        .filter((item) => Number.isFinite(item.value) && item.value > 0)
        .sort((a, b) => a.index - b.index);
}

function calculateCurrentStreak() {
    let streak = 0;
    const currentDayIndex = getCurrentDayIndex();
    for (let day = currentDayIndex; day >= 1; day -= 1) {
        if (state.logs[String(day)]?.completed) {
            streak += 1;
        } else {
            break;
        }
    }
    return streak;
}

function createDefaultState() {
    const logs = {};
    for (let day = 1; day <= 30; day += 1) {
        logs[String(day)] = createEmptyLog();
    }

    return {
        profile: { ...defaultProfile },
        selectedDay: 1,
        logs
    };
}

function createEmptyLog() {
    return {
        weight: '',
        sleepHours: '',
        walkMinutes: '',
        energy: '',
        note: '',
        completed: false,
        completedAt: '',
        tasks: {}
    };
}

function loadState() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return normalizeState(raw ? JSON.parse(raw) : createDefaultState());
    } catch (error) {
        return createDefaultState();
    }
}

function normalizeState(input) {
    const base = createDefaultState();
    const merged = {
        profile: {
            ...base.profile,
            ...(input?.profile || {})
        },
        selectedDay: clampNumber(Number(input?.selectedDay), 1, 30, getCurrentDayIndexSafe(input?.profile?.startDate)),
        logs: { ...base.logs }
    };

    for (let day = 1; day <= 30; day += 1) {
        const key = String(day);
        merged.logs[key] = {
            ...createEmptyLog(),
            ...(input?.logs?.[key] || {}),
            tasks: { ...(input?.logs?.[key]?.tasks || {}) }
        };
    }

    return merged;
}

function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function todayISO() {
    const now = new Date();
    const offset = now.getTimezoneOffset();
    return new Date(now.getTime() - offset * 60000).toISOString().slice(0, 10);
}

function parseDateOnly(value) {
    const [year, month, day] = String(value).split('-').map(Number);
    return new Date(year, (month || 1) - 1, day || 1);
}

function formatDate(value) {
    return value.toLocaleDateString('zh-CN', {
        month: 'numeric',
        day: 'numeric',
        weekday: 'short'
    });
}

function formatWeightDelta(value) {
    const prefix = value > 0 ? '+' : '';
    return `${prefix}${value.toFixed(1)} kg`;
}

function clampNumber(value, min, max, fallback) {
    if (!Number.isFinite(value)) return fallback;
    return Math.min(max, Math.max(min, value));
}

function getCurrentDayIndexSafe(startDate) {
    const start = parseDateOnly(startDate || todayISO());
    const today = parseDateOnly(todayISO());
    const diffDays = Math.floor((today - start) / 86400000) + 1;
    if (diffDays < 1) return 1;
    if (diffDays > 30) return 30;
    return diffDays;
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

let toastTimer = null;

function showToast(message) {
    let toast = document.querySelector('.toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.className = 'toast';
        document.body.appendChild(toast);
    }

    toast.textContent = message;
    toast.classList.add('visible');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
        toast.classList.remove('visible');
    }, 1800);
}
