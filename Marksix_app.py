# Marksix_app.py
import streamlit as st
import pandas as pd
import numpy as np
import random
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# 页面配置
st.set_page_config(
    page_title="六合彩AI分析工具 - DFSS智能选号",
    page_icon="🎰",
    layout="wide"
)

# ==================== 理论介绍（左侧边栏） ====================
with st.sidebar:
    st.title("🎰 六合彩AI分析工具")
    st.markdown("---")
    
    with st.expander("📖 中央趋向定理", expanded=False):
        st.markdown("""
        - 从49个球抽取7个球，和值呈正态分布
        - 理论和值: (1+49)/2 * 7 = 175
        - 标准差: 约 35
        - 约68%的组合和值在 140-210 之间
        """)
    
    with st.expander("🔥 冷热码计算公式", expanded=False):
        st.latex(r"""
        \text{Score}_i = 0.3 \cdot \frac{F_i - E}{\sigma_F} + 
        0.3 \cdot \frac{A_i - \mu_A}{\sigma_A} + 
        0.2 \cdot \frac{R_i - E_R}{\sigma_R} + 
        0.2 \cdot \text{Recent}_i
        """)
        st.markdown("""
        | 参数 | 含义 |
        |------|------|
        | F_i | 历史总频次 |
        | A_i | 当前缺席次数 |
        | R_i | 短期频次(20期) |
        | Recent_i | 近10期是否出现 |
        """)
    
    with st.expander("📊 连号/跳号概率", expanded=False):
        st.markdown("""
        - 至少一对连号: 55.6%
        - 至少一对跳号: 65%
        - 同时包含: 约35%
        """)
    
    with st.expander("💰 奖金结构", expanded=False):
        st.markdown("""
        | 等级 | 匹配 | 奖金 |
        |------|------|------|
        | 第1组 | 7 | 45%基金 |
        | 第2组 | 6+特 | 15%基金 |
        | 第3组 | 6 | 40%基金 |
        | 第4组 | 5+特 | $9,600 |
        | 第5组 | 5 | $640 |
        | 第6组 | 4+特 | $320 |
        | 第7组 | 4 | $40 |
        """)

# ==================== 核心函数 ====================

def parse_pasted_data(text):
    """解析粘贴的数据文本"""
    lines = text.strip().split('\n')
    draws = []
    
    for line in lines:
        if not line.strip():
            continue
        
        # 用制表符、逗号或空格分割
        parts = line.replace(',', '\t').replace(' ', '\t').split('\t')
        parts = [p.strip() for p in parts if p.strip()]
        
        if len(parts) >= 9:
            try:
                nums = []
                for i in range(2, 9):
                    if i < len(parts):
                        num = int(float(parts[i]))
                        nums.append(num)
                
                if len(nums) == 7:
                    draws.append({
                        'period': parts[0],
                        'date': parts[1] if len(parts) > 1 else None,
                        'numbers': sorted(nums[:6]),
                        'special': nums[6],
                        'sum': sum(nums[:6])
                    })
            except (ValueError, IndexError):
                continue
    
    return draws

def parse_excel_file(uploaded_file):
    """解析Excel文件"""
    try:
        df = pd.read_excel(uploaded_file, sheet_name=0)
        number_cols = ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7']
        existing_cols = [col for col in number_cols if col in df.columns]
        
        if len(existing_cols) >= 7:
            draws = []
            for idx, row in df.iterrows():
                try:
                    nums = []
                    for col in existing_cols[:6]:
                        val = row[col]
                        if pd.notna(val):
                            nums.append(int(val))
                    
                    special = None
                    if len(existing_cols) > 6:
                        special_val = row[existing_cols[6]]
                        if pd.notna(special_val):
                            special = int(special_val)
                    
                    if len(nums) == 6:
                        draws.append({
                            'period': row.get('期次', idx+1),
                            'date': row.get('開獎日期', None),
                            'numbers': sorted(nums),
                            'special': special,
                            'sum': sum(nums)
                        })
                except (ValueError, TypeError):
                    continue
            return draws
    except Exception as e:
        st.error(f"Excel解析错误: {e}")
        return None

def calculate_scores(draws, window_total=100, window_short=20, window_recent=10):
    """计算每个号码的综合得分"""
    if len(draws) < window_total:
        window_total = len(draws)
    
    total_draws = len(draws)
    expected_freq = total_draws * 6 / 49
    
    freq = {i: 0 for i in range(1, 50)}
    for draw in draws[-window_total:]:
        for num in draw['numbers']:
            freq[num] += 1
    
    short_freq = {i: 0 for i in range(1, 50)}
    for draw in draws[-window_short:]:
        for num in draw['numbers']:
            short_freq[num] += 1
    expected_short = window_short * 6 / 49
    
    last_seen = {i: None for i in range(1, 50)}
    for idx, draw in enumerate(reversed(draws)):
        for num in draw['numbers']:
            if last_seen[num] is None:
                last_seen[num] = idx
    absence = {i: last_seen[i] if last_seen[i] is not None else total_draws for i in range(1, 50)}
    
    recent_numbers = set()
    for draw in draws[-window_recent:]:
        recent_numbers.update(draw['numbers'])
    
    freq_mean = expected_freq
    freq_std = np.std(list(freq.values())) if len(freq.values()) > 1 else 1
    absence_mean = np.mean(list(absence.values()))
    absence_std = np.std(list(absence.values())) if len(absence.values()) > 1 else 1
    short_mean = expected_short
    short_std = np.std(list(short_freq.values())) if len(short_freq.values()) > 1 else 1
    
    scores = {}
    for i in range(1, 50):
        z_freq = (freq[i] - freq_mean) / freq_std if freq_std > 0 else 0
        z_absence = (absence[i] - absence_mean) / absence_std if absence_std > 0 else 0
        z_short = (short_freq[i] - short_mean) / short_std if short_std > 0 else 0
        recent_active = 1 if i in recent_numbers else -1
        
        score = 0.3 * z_freq + 0.3 * z_absence + 0.2 * z_short + 0.2 * recent_active
        scores[i] = score
    
    return scores, freq, short_freq, absence

def has_consecutive_or_jump(nums):
    """检查是否有连号或跳号"""
    nums = sorted(nums)
    for i in range(len(nums)-1):
        diff = nums[i+1] - nums[i]
        if diff == 1 or diff == 2:
            return True
    return False

def generate_combination(scores, target_sum, tolerance=15, require_pattern=True):
    """生成符合条件的一组号码"""
    min_sum = target_sum - tolerance
    max_sum = target_sum + tolerance
    
    sorted_numbers = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    hot_numbers = sorted_numbers[:15]
    cold_numbers = sorted_numbers[-10:]
    
    max_attempts = 50000
    for _ in range(max_attempts):
        selected = set()
        
        num_hot = random.randint(2, 3)
        hot_pool = [n for n in hot_numbers if n not in selected]
        if len(hot_pool) >= num_hot:
            selected.update(random.sample(hot_pool, num_hot))
        
        remaining = [n for n in range(1, 50) if n not in selected and n not in cold_numbers[:5]]
        if len(remaining) < 6 - len(selected):
            continue
        selected.update(random.sample(remaining, 6 - len(selected)))
        
        nums = sorted(selected)
        total = sum(nums)
        
        if min_sum <= total <= max_sum:
            if not require_pattern or has_consecutive_or_jump(nums):
                return nums, total
    
    for _ in range(10000):
        nums = sorted(random.sample(range(1, 50), 6))
        total = sum(nums)
        if min_sum <= total <= max_sum:
            return nums, total
    
    return sorted(random.sample(range(1, 50), 6)), sum(sorted(random.sample(range(1, 50), 6)))

def predict_trend(draws, window=5):
    """根据最近window期的和值预测下一期趋势"""
    if len(draws) < window:
        return 175
    
    recent_sums = [draw['sum'] for draw in draws[-window:]]
    avg_sum = np.mean(recent_sums)
    
    if avg_sum > 185:
        return 160
    elif avg_sum < 165:
        return 190
    else:
        return 175

def generate_optimal_bets(draws, num_bets, scores):
    """根据用户输入的注数，生成最优投注组合"""
    bets = []
    
    if num_bets == 1:
        nums, total = generate_combination(scores, 175)
        bets.append({'numbers': nums, 'sum': total, 'strategy': '中和值'})
    
    elif num_bets == 2:
        nums1, total1 = generate_combination(scores, 155)
        nums2, total2 = generate_combination(scores, 195)
        bets.append({'numbers': nums1, 'sum': total1, 'strategy': '小和值'})
        bets.append({'numbers': nums2, 'sum': total2, 'strategy': '大和值'})
    
    elif num_bets == 3:
        nums1, total1 = generate_combination(scores, 155)
        nums2, total2 = generate_combination(scores, 175)
        nums3, total3 = generate_combination(scores, 195)
        bets.append({'numbers': nums1, 'sum': total1, 'strategy': '小和值'})
        bets.append({'numbers': nums2, 'sum': total2, 'strategy': '中和值'})
        bets.append({'numbers': nums3, 'sum': total3, 'strategy': '大和值'})
    
    else:
        nums1, total1 = generate_combination(scores, 155)
        nums2, total2 = generate_combination(scores, 175)
        nums3, total3 = generate_combination(scores, 195)
        bets = [
            {'numbers': nums1, 'sum': total1, 'strategy': '小和值'},
            {'numbers': nums2, 'sum': total2, 'strategy': '中和值'},
            {'numbers': nums3, 'sum': total3, 'strategy': '大和值'}
        ]
        
        for i in range(num_bets - 3):
            trend_target = predict_trend(draws)
            nums, total = generate_combination(scores, trend_target)
            bets.append({'numbers': nums, 'sum': total, 'strategy': f'趋势预测(目标{trend_target})'})
    
    return bets

def calculate_prize(match_count, special_match):
    """根据匹配数计算奖金"""
    if match_count == 6:
        return "第1组 (45%基金)"
    elif match_count == 5 and special_match:
        return "第2组 (15%基金)"
    elif match_count == 5:
        return "第3组 (40%基金)"
    elif match_count == 4 and special_match:
        return "第4组 ($9,600)"
    elif match_count == 4:
        return "第5组 ($640)"
    elif match_count == 3 and special_match:
        return "第6组 ($320)"
    elif match_count == 3:
        return "第7组 ($40)"
    else:
        return "无中奖"

def backtest(draws, scores, num_bets_per_draw=4):
    """回测策略"""
    results = []
    min_train = min(100, len(draws) // 2)
    
    for i in range(min_train, len(draws)):
        train_draws = draws[:i]
        test_draw = draws[i]
        
        train_scores, _, _, _ = calculate_scores(train_draws)
        bets = generate_optimal_bets(train_draws, num_bets_per_draw, train_scores)
        
        best_match = 0
        best_special_match = False
        best_prize = "无中奖"
        
        for bet in bets:
            match_count = len(set(bet['numbers']) & set(test_draw['numbers']))
            special_match = test_draw.get('special') in bet['numbers'] if test_draw.get('special') else False
            
            if match_count > best_match or (match_count == best_match and special_match):
                best_match = match_count
                best_special_match = special_match
                best_prize = calculate_prize(match_count, special_match)
        
        results.append({
            '期次': test_draw.get('period', i+1),
            '真实号码': str(test_draw['numbers']),
            '真实和值': test_draw['sum'],
            '最佳匹配数': best_match,
            '特别号匹配': best_special_match,
            '中奖等级': best_prize
        })
    
    return pd.DataFrame(results)

# ==================== 主页面 ====================

st.title("🎯 六合彩AI智能选号工具")

# 数据输入方式选择
st.subheader("📁 数据输入")
input_method = st.radio(
    "选择输入方式",
    ["📋 粘贴数据", "📁 上传Excel文件"],
    horizontal=True
)

draws = None

if input_method == "📋 粘贴数据":
    st.markdown("""
    **数据格式说明**: 每期一行，格式如下
    期次 日期 B1 B2 B3 B4 B5 B6 B7
    26045 2026-04-25 4 16 21 36 42 46 9
    支持制表符、逗号或空格分隔，至少需要8列
    """)
    
    example_data = """26045	2026-04-25	4	16	21	36	42	46	9
26044	2026-04-23	12	23	37	38	45	48	8
26043	2026-04-21	2	4	10	11	26	44	40
26042	2026-04-18	17	20	27	32	39	46	34
26041	2026-04-16	6	12	14	28	44	46	15
26040	2026-04-14	8	19	22	33	44	46	18
26039	2026-04-11	11	14	17	28	40	42	2
26038	2026-04-09	13	16	24	43	44	45	40
26037	2026-04-07	8	23	25	29	33	34	49
26036	2026-04-04	20	28	32	35	40	45	43"""
    
    pasted_text = st.text_area(
        "粘贴开奖数据",
        value=example_data,
        height=300,
        help="每期一行，至少包含期次、日期、B1-B7共9列"
    )
    
    if pasted_text:
        lines = pasted_text.strip().split('\n')
        preview_lines = lines[:30]
        
        st.markdown(f"**数据预览** (共 {len(lines)} 期，显示前 {min(30, len(lines))} 期)")
        
        preview_data = []
        for line in preview_lines:
            parts = line.replace(',', '\t').replace(' ', '\t').split('\t')
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) >= 9:
                preview_data.append({
                    '期次': parts[0],
                    '日期': parts[1],
                    'B1': parts[2], 'B2': parts[3], 'B3': parts[4],
                    'B4': parts[5], 'B5': parts[6], 'B6': parts[7], 'B7': parts[8]
                })
        
        if preview_data:
            preview_df = pd.DataFrame(preview_data)
            st.dataframe(preview_df, use_container_width=True, height=400)
        
        if len(lines) > 30:
            st.caption(f"还有 {len(lines) - 30} 期未显示，可滚动上方文本框查看全部")
        
        if st.button("确认并解析数据", type="primary"):
            draws = parse_pasted_data(pasted_text)
            if draws and len(draws) > 0:
                st.success(f"成功解析 {len(draws)} 期数据")
            else:
                st.error("解析失败，请检查数据格式")

else:
    uploaded_file = st.file_uploader("上传历史开奖数据 (Excel格式)", type=['xlsx', 'xls'])
    if uploaded_file is not None:
        draws = parse_excel_file(uploaded_file)
        if draws and len(draws) > 0:
            st.success(f"成功加载 {len(draws)} 期数据")
            
            with st.expander("数据预览 (前30期)"):
                preview_df = pd.DataFrame([
                    {'期次': draw.get('period', i+1), '号码': draw['numbers'], '和值': draw['sum'], '特别号': draw.get('special', '')}
                    for i, draw in enumerate(draws[:30])
                ])
                st.dataframe(preview_df, use_container_width=True)
                if len(draws) > 30:
                    st.caption(f"还有 {len(draws) - 30} 期未显示")

if draws and len(draws) > 0:
    st.markdown("---")
    
    scores, freq, short_freq, absence = calculate_scores(draws)
    
    st.subheader("🔥 冷热码分析")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**热门号码 (Top 10)**")
        hot_df = pd.DataFrame([
            {'号码': num, '得分': f"{scores[num]:.2f}", '总次数': freq[num], '缺席次数': absence[num]}
            for num in sorted(scores, key=scores.get, reverse=True)[:10]
        ])
        st.dataframe(hot_df, use_container_width=True)
    
    with col2:
        st.markdown("**冷门号码 (Bottom 10)**")
        cold_df = pd.DataFrame([
            {'号码': num, '得分': f"{scores[num]:.2f}", '总次数': freq[num], '缺席次数': absence[num]}
            for num in sorted(scores, key=scores.get)[:10]
        ])
        st.dataframe(cold_df, use_container_width=True)
    
    with col3:
        st.markdown("**近期活跃**")
        recent_active = [num for num in range(1, 50) if any(num in draw['numbers'] for draw in draws[-10:])]
        st.write(f"近10期出现过的号码: {len(recent_active)}个")
        st.write(sorted(recent_active)[:15], "...")
    
    st.subheader("📈 和值趋势分析")
    sum_df = pd.DataFrame([
        {'期次': i+1, '和值': draw['sum']}
        for i, draw in enumerate(draws)
    ])
    fig = px.line(sum_df, x='期次', y='和值', title='历史和值走势')
    fig.add_hline(y=175, line_dash="dash", line_color="red", annotation_text="理论均值(175)")
    fig.add_hrect(y0=140, y1=210, line_width=0, fillcolor="green", opacity=0.1, annotation_text="约68%区间")
    st.plotly_chart(fig, use_container_width=True)
    
    st.subheader("🎲 智能投注生成")
    
    col1, col2 = st.columns(2)
    with col1:
        num_bets = st.number_input("请输入投注注数", min_value=1, max_value=10, value=4, step=1)
    with col2:
        st.markdown("**策略说明**")
        if num_bets == 1:
            st.info("单注: 中和值(175) + 热码优先 + 连号/跳号")
        elif num_bets == 2:
            st.info("两注: 小和值(155) + 大和值(195)")
        elif num_bets == 3:
            st.info("三注: 小(155) + 中(175) + 大(195)")
        else:
            st.info(f"{num_bets}注: 大中小各一 + {num_bets-3}注趋势预测")
    
    if st.button("生成智能投注", type="primary"):
        bets = generate_optimal_bets(draws, num_bets, scores)
        
        st.markdown("### 推荐投注组合")
        
        for i, bet in enumerate(bets, 1):
            with st.container():
                st.markdown(f"**第{i}注** - 策略: {bet['strategy']}")
                col_a, col_b, col_c = st.columns([2, 1, 1])
                with col_a:
                    st.write(f"号码: {bet['numbers']}")
                with col_b:
                    st.write(f"和值: {bet['sum']}")
                with col_c:
                    diff_val = bet['sum'] - 175
                    st.write(f"偏差: {diff_val:+d}")
                
                has_pattern = has_consecutive_or_jump(bet['numbers'])
                st.caption(f"包含连号/跳号: {'是' if has_pattern else '否'}")
                st.divider()
        
        st.info("""
        **关于预测赢率**:
        - 本工具基于历史数据统计，预测中奖率约 6-7% (中3个或以上)
        - 实际中奖率受随机性影响，长期期望值仍为负
        - 建议理性投注，量力而行
        """)
    
    st.subheader("📊 策略回测")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        backtest_bets = st.number_input("回测投注注数", min_value=1, max_value=10, value=4, step=1, key="backtest")
        run_backtest = st.button("运行回测", type="secondary")
    
    with col2:
        st.info("回测使用前100期训练，预测后续所有期次")
    
    if run_backtest:
        with st.spinner("正在运行回测..."):
            if len(draws) > 100:
                results_df = backtest(draws, scores, backtest_bets)
                
                st.markdown("### 回测结果统计")
                
                stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
                
                total_draws_count = len(results_df)
                winning_draws_count = results_df[results_df['中奖等级'] != '无中奖'].shape[0]
                avg_match_val = results_df['最佳匹配数'].mean()
                
                prize_map = {
                    '第4组 ($9,600)': 9600,
                    '第5组 ($640)': 640,
                    '第6组 ($320)': 320,
                    '第7组 ($40)': 40,
                }
                
                total_prize = 0
                for prize in results_df['中奖等级']:
                    if prize in prize_map:
                        total_prize += prize_map[prize]
                
                total_cost = len(results_df) * backtest_bets * 10
                
                with stat_col1:
                    st.metric("测试期数", total_draws_count)
                with stat_col2:
                    st.metric("中奖期数", winning_draws_count)
                with stat_col3:
                    st.metric("平均匹配数", f"{avg_match_val:.2f}")
                with stat_col4:
                    roi_val = ((total_prize - total_cost) / total_cost) * 100 if total_cost > 0 else 0
                    st.metric("投资回报率(ROI)", f"{roi_val:+.1f}%")
                
                st.markdown(f"**总投入**: ${total_cost} | **总奖金**: ${total_prize} | **净收益**: ${total_prize - total_cost}")
                
                with st.expander("详细回测结果"):
                    st.dataframe(results_df, use_container_width=True)
                
                match_dist = results_df['最佳匹配数'].value_counts().sort_index()
                fig_match = px.bar(
                    x=match_dist.index, y=match_dist.values,
                    title='每期最佳匹配数分布',
                    labels={'x': '匹配号码数', 'y': '期数'}
                )
                st.plotly_chart(fig_match, use_container_width=True)
            else:
                st.warning(f"需要至少100期数据才能进行回测，当前只有{len(draws)}期")

st.markdown("---")
st.caption("注意: 本工具仅供学术研究和娱乐参考。六合彩本质上是一种随机游戏，长期期望值为负，请理性投注。")
