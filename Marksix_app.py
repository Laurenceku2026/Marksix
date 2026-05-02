# app.py
import streamlit as st
import pandas as pd
import numpy as np
import itertools
import random
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
from io import StringIO

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
        - 理论和值：**(1+49)/2 × 7 = 175**
        - 标准差：**σ ≈ 35**
        - 约68%的组合和值在 **140~210** 之间
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
        - 至少一对连号：**55.6%**
        - 至少一对跳号：**65%**
        - 同时包含：**约35%**
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

def load_data(uploaded_file):
    """加载用户上传的Excel文件"""
    if uploaded_file is not None:
        df = pd.read_excel(uploaded_file, sheet_name=0)
        # 查找包含号码的列（B1-B7）
        number_cols = ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7']
        existing_cols = [col for col in number_cols if col in df.columns]
        
        if len(existing_cols) == 7:
            # 提取号码
            draws = []
            for _, row in df.iterrows():
                nums = sorted([int(row[col]) for col in existing_cols if pd.notna(row[col])])
                if len(nums) == 7:
                    special = int(row['B7']) if 'B7' in df.columns and pd.notna(row['B7']) else None
                    draws.append({
                        'numbers': nums,
                        'special': special,
                        'sum': sum(nums),
                        'date': row.get('開獎日期', None)
                    })
            return draws
    return None

def calculate_scores(draws, window_total=100, window_short=20, window_recent=10):
    """计算每个号码的综合得分"""
    if len(draws) < window_total:
        window_total = len(draws)
    
    total_draws = len(draws)
    expected_freq = total_draws * 7 / 49
    
    # 统计每个号码的出现次数
    freq = {i: 0 for i in range(1, 50)}
    for draw in draws[-window_total:]:
        for num in draw['numbers']:
            freq[num] += 1
    
    # 短期频次
    short_freq = {i: 0 for i in range(1, 50)}
    for draw in draws[-window_short:]:
        for num in draw['numbers']:
            short_freq[num] += 1
    expected_short = window_short * 7 / 49
    
    # 缺席次数
    last_seen = {i: None for i in range(1, 50)}
    for idx, draw in enumerate(reversed(draws)):
        for num in draw['numbers']:
            if last_seen[num] is None:
                last_seen[num] = idx
    absence = {i: last_seen[i] if last_seen[i] is not None else total_draws for i in range(1, 50)}
    
    # 近期活跃度（最近recent期）
    recent_numbers = set()
    for draw in draws[-window_recent:]:
        recent_numbers.update(draw['numbers'])
    
    # 计算标准化分数
    freq_mean = expected_freq
    freq_std = np.std(list(freq.values()))
    absence_mean = np.mean(list(absence.values()))
    absence_std = np.std(list(absence.values()))
    short_mean = expected_short
    short_std = np.std(list(short_freq.values()))
    
    scores = {}
    for i in range(1, 50):
        z_freq = (freq[i] - freq_mean) / freq_std if freq_std > 0 else 0
        z_absence = (absence[i] - absence_mean) / absence_std if absence_std > 0 else 0
        z_short = (short_freq[i] - short_mean) / short_std if short_std > 0 else 0
        recent_active = 1 if i in recent_numbers else -1
        
        # 权重：长期30% + 缺席30% + 短期20% + 近期20%
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
    
    # 按得分排序
    sorted_numbers = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    hot_numbers = sorted_numbers[:15]  # 前15个热码
    cold_numbers = sorted_numbers[-10:]  # 后10个冷码
    
    max_attempts = 50000
    for _ in range(max_attempts):
        # 策略：优先从热码中选2-3个
        selected = set()
        
        # 选2-3个热码
        num_hot = random.randint(2, 3)
        hot_pool = [n for n in hot_numbers if n not in selected]
        if len(hot_pool) >= num_hot:
            selected.update(random.sample(hot_pool, num_hot))
        
        # 从剩余号码中选满7个（避开冷码）
        remaining = [n for n in range(1, 50) if n not in selected and n not in cold_numbers[:5]]
        if len(remaining) < 7 - len(selected):
            continue
        selected.update(random.sample(remaining, 7 - len(selected)))
        
        nums = sorted(selected)
        total = sum(nums)
        
        # 检查约束
        if min_sum <= total <= max_sum:
            if not require_pattern or has_consecutive_or_jump(nums):
                return nums, total
    
    # 降级：放宽条件
    for _ in range(10000):
        nums = sorted(random.sample(range(1, 50), 7))
        total = sum(nums)
        if min_sum <= total <= max_sum:
            return nums, total
    
    return sorted(random.sample(range(1, 50), 7)), sum(sorted(random.sample(range(1, 50), 7)))

def predict_trend(draws, window=5):
    """根据最近window期的和值预测下一期趋势"""
    if len(draws) < window:
        return 175
    
    recent_sums = [draw['sum'] for draw in draws[-window:]]
    avg_sum = np.mean(recent_sums)
    
    if avg_sum > 185:
        # 和值偏大，预测偏小
        return 160
    elif avg_sum < 165:
        # 和值偏小，预测偏大
        return 190
    else:
        return 175

def generate_optimal_bets(draws, num_bets, scores):
    """根据用户输入的注数，生成最优投注组合"""
    bets = []
    
    # 计算最近30期的和值分布
    if len(draws) >= 30:
        recent_sums = [draw['sum'] for draw in draws[-30:]]
        sum_mean = np.mean(recent_sums)
        sum_std = np.std(recent_sums)
    else:
        sum_mean = 175
        sum_std = 35
    
    if num_bets == 1:
        # 单注：中和值
        nums, total = generate_combination(scores, 175)
        bets.append({'numbers': nums, 'sum': total, 'strategy': '中和值'})
    
    elif num_bets == 2:
        # 两注：小+大
        nums1, total1 = generate_combination(scores, 155)
        nums2, total2 = generate_combination(scores, 195)
        bets.append({'numbers': nums1, 'sum': total1, 'strategy': '小和值'})
        bets.append({'numbers': nums2, 'sum': total2, 'strategy': '大和值'})
    
    elif num_bets == 3:
        # 三注：大中小
        nums1, total1 = generate_combination(scores, 155)
        nums2, total2 = generate_combination(scores, 175)
        nums3, total3 = generate_combination(scores, 195)
        bets.append({'numbers': nums1, 'sum': total1, 'strategy': '小和值'})
        bets.append({'numbers': nums2, 'sum': total2, 'strategy': '中和值'})
        bets.append({'numbers': nums3, 'sum': total3, 'strategy': '大和值'})
    
    else:
        # 4注及以上：大中小 + 趋势预测
        nums1, total1 = generate_combination(scores, 155)
        nums2, total2 = generate_combination(scores, 175)
        nums3, total3 = generate_combination(scores, 195)
        bets = [
            {'numbers': nums1, 'sum': total1, 'strategy': '小和值'},
            {'numbers': nums2, 'sum': total2, 'strategy': '中和值'},
            {'numbers': nums3, 'sum': total3, 'strategy': '大和值'}
        ]
        
        # 额外注数用趋势预测
        for i in range(num_bets - 3):
            trend_target = predict_trend(draws)
            nums, total = generate_combination(scores, trend_target)
            bets.append({'numbers': nums, 'sum': total, 'strategy': f'趋势预测(目标{trend_target})'})
    
    return bets

def calculate_prize(match_count, special_match):
    """根据匹配数计算奖金"""
    if match_count == 7:
        return "第1组 (45%基金)"
    elif match_count == 6 and special_match:
        return "第2组 (15%基金)"
    elif match_count == 6:
        return "第3组 (40%基金)"
    elif match_count == 5 and special_match:
        return "第4组 ($9,600)"
    elif match_count == 5:
        return "第5组 ($640)"
    elif match_count == 4 and special_match:
        return "第6组 ($320)"
    elif match_count == 4:
        return "第7组 ($40)"
    else:
        return "无中奖"

def backtest(draws, scores, num_bets_per_draw=4):
    """回测策略"""
    results = []
    
    for i in range(100, len(draws)):
        # 用前i期数据训练
        train_draws = draws[:i]
        test_draw = draws[i]
        
        # 重新计算得分
        train_scores, _, _, _ = calculate_scores(train_draws)
        
        # 生成投注
        bets = generate_optimal_bets(train_draws, num_bets_per_draw, train_scores)
        
        # 检查中奖情况
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
            '期次': i+1,
            '真实号码': test_draw['numbers'],
            '真实和值': test_draw['sum'],
            '最佳匹配数': best_match,
            '特别号匹配': best_special_match,
            '中奖等级': best_prize
        })
    
    return pd.DataFrame(results)

# ==================== 主页面 ====================

st.title("🎯 六合彩AI智能选号工具")

# 数据上传
st.subheader("📁 数据上传")
uploaded_file = st.file_uploader("上传历史开奖数据 (Excel格式)", type=['xlsx', 'xls'])

if uploaded_file is not None:
    draws = load_data(uploaded_file)
    
    if draws and len(draws) > 0:
        st.success(f"✅ 成功加载 {len(draws)} 期数据")
        
        # 显示数据预览
        with st.expander("📊 数据预览"):
            preview_df = pd.DataFrame([
                {'期次': i+1, '号码': draw['numbers'], '和值': draw['sum'], '特别号': draw.get('special', '')}
                for i, draw in enumerate(draws[-20:])
            ])
            st.dataframe(preview_df)
        
        # 计算冷热码
        scores, freq, short_freq, absence = calculate_scores(draws)
        
        # 显示冷热码分析
        st.subheader("🔥 冷热码分析")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("**🔥 热门号码 (Top 10)**")
            hot_df = pd.DataFrame([
                {'号码': num, '得分': scores[num], '总次数': freq[num], '缺席次数': absence[num]}
                for num in sorted(scores, key=scores.get, reverse=True)[:10]
            ])
            st.dataframe(hot_df)
        
        with col2:
            st.markdown("**❄️ 冷门号码 (Bottom 10)**")
            cold_df = pd.DataFrame([
                {'号码': num, '得分': scores[num], '总次数': freq[num], '缺席次数': absence[num]}
                for num in sorted(scores, key=scores.get)[:10]
            ])
            st.dataframe(cold_df)
        
        with col3:
            st.markdown("**📈 近期活跃**")
            recent_active = [num for num in range(1, 50) if any(num in draw['numbers'] for draw in draws[-10:])]
            st.write(f"近10期出现过的号码: {len(recent_active)}个")
            st.write(sorted(recent_active)[:15], "...")
        
        # 和值分布图
        st.subheader("📈 和值趋势分析")
        sum_df = pd.DataFrame([
            {'期次': i+1, '和值': draw['sum']}
            for i, draw in enumerate(draws)
        ])
        fig = px.line(sum_df, x='期次', y='和值', title='历史和值走势')
        fig.add_hline(y=175, line_dash="dash", line_color="red", annotation_text="理论均值(175)")
        fig.add_hrect(y0=140, y1=210, line_width=0, fillcolor="green", opacity=0.1, annotation_text="±1σ区间")
        st.plotly_chart(fig, use_container_width=True)
        
        # 投注设置
        st.subheader("🎲 智能投注生成")
        
        col1, col2 = st.columns(2)
        with col1:
            num_bets = st.number_input("请输入投注注数", min_value=1, max_value=10, value=4, step=1)
        with col2:
            st.markdown("**💡 策略说明**")
            if num_bets == 1:
                st.info("单注：中和值(175) + 热码优先 + 连号/跳号")
            elif num_bets == 2:
                st.info("两注：小和值(155) + 大和值(195)")
            elif num_bets == 3:
                st.info("三注：小(155) + 中(175) + 大(195)")
            else:
                st.info(f"{num_bets}注：大中小各一 + {num_bets-3}注趋势预测")
        
        # 生成投注
        if st.button("🚀 生成智能投注", type="primary"):
            bets = generate_optimal_bets(draws, num_bets, scores)
            
            st.markdown("### 📝 推荐投注组合")
            
            for i, bet in enumerate(bets, 1):
                with st.container():
                    st.markdown(f"**第{i}注** - 策略: {bet['strategy']}")
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1:
                        st.write(f"号码: {bet['numbers']}")
                    with col2:
                        st.write(f"和值: {bet['sum']}")
                    with col3:
                        diff = bet['sum'] - 175
                        st.write(f"偏差: {diff:+d}")
                    
                    # 显示特征
                    has_pattern = has_consecutive_or_jump(bet['numbers'])
                    st.caption(f"包含连号/跳号: {'✅' if has_pattern else '❌'}")
                    st.divider()
        
        # 回测功能
        st.subheader("📊 策略回测")
        
        col1, col2 = st.columns([1, 2])
        with col1:
            backtest_bets = st.number_input("回测投注注数", min_value=1, max_value=10, value=4, step=1)
            run_backtest = st.button("▶️ 运行回测", type="secondary")
        
        with col2:
            st.info("回测使用前100期训练，预测后续所有期次")
        
        if run_backtest:
            with st.spinner("正在运行回测..."):
                results_df = backtest(draws, scores, backtest_bets)
                
                # 统计结果
                st.markdown("### 📈 回测结果统计")
                
                stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
                
                total_draws = len(results_df)
                winning_draws = results_df[results_df['中奖等级'] != '无中奖'].shape[0]
                avg_match = results_df['最佳匹配数'].mean()
                
                # 计算投注回报（假设每注$10）
                prize_map = {
                    '第7组 ($40)': 40,
                    '第6组 ($320)': 320,
                    '第5组 ($640)': 640,
                    '第4组 ($9,600)': 9600,
                }
                
                total_prize = 0
                for prize in results_df['中奖等级']:
                    if prize in prize_map:
                        total_prize += prize_map[prize]
                
                total_cost = len(results_df) * backtest_bets * 10
                
                with stat_col1:
                    st.metric("测试期数", total_draws)
                with stat_col2:
                    st.metric("中奖期数", winning_draws)
                with stat_col3:
                    st.metric("平均匹配数", f"{avg_match:.2f}")
                with stat_col4:
                    roi = ((total_prize - total_cost) / total_cost) * 100
                    st.metric("投资回报率(ROI)", f"{roi:+.1f}%", delta_color="normal")
                
                st.markdown(f"**总投入**: ${total_cost} | **总奖金**: ${total_prize} | **净收益**: ${total_prize - total_cost}")
                
                # 显示详细结果
                with st.expander("📋 详细回测结果"):
                    st.dataframe(results_df)
                
                # 匹配数分布图
                match_dist = results_df['最佳匹配数'].value_counts().sort_index()
                fig_match = px.bar(
                    x=match_dist.index, y=match_dist.values,
                    title='每期最佳匹配数分布',
                    labels={'x': '匹配号码数', 'y': '期数'}
                )
                st.plotly_chart(fig_match, use_container_width=True)
        
    else:
        st.error("❌ 无法解析数据文件，请确保包含B1-B7列")
else:
    st.info("👈 请先上传历史开奖数据（Excel格式）")
    
    # 示例说明
    with st.expander("📖 数据格式说明"):
        st.markdown("""
        Excel文件应包含以下列：
        - **B1, B2, B3, B4, B5, B6**: 6个正码
        - **B7**: 特别号码
        - **開獎日期**: 开奖日期（可选）
        
        示例格式：
        | 期次 | 開獎日期 | B1 | B2 | B3 | B4 | B5 | B6 | B7 |
        |------|----------|----|----|----|----|----|----|-----|
        | 26045| 2026-04-25| 4  | 16 | 21 | 36 | 42 | 46 | 9   |
        """)

# 页脚
st.markdown("---")
st.caption("⚠️ 本工具仅供学术研究和娱乐参考。六合彩本质上是一种随机游戏，长期期望值为负，请理性投注。")
