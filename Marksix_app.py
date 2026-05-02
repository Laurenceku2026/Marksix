# Marksix_app.py
import streamlit as st
import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import hashlib
import hmac
from supabase import create_client, Client

# 页面配置
st.set_page_config(
    page_title="六合彩AI分析工具 - DFSS智能选号",
    page_icon="🎰",
    layout="wide"
)

# ==================== Supabase 初始化 ====================
def init_supabase():
    """初始化Supabase客户端"""
    try:
        supabase_url = st.secrets["SUPABASE_URL"]
        supabase_key = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
        return create_client(supabase_url, supabase_key)
    except Exception as e:
        st.error(f"Supabase连接失败: {e}")
        return None

def save_draws_to_supabase(draws):
    """保存开奖数据到Supabase（覆盖保存）"""
    supabase = init_supabase()
    if supabase is None:
        return False
    
    try:
        table = supabase.schema('marksix_schema').table('marksix_draws')
        table.delete().neq("id", 0).execute()
        
        for draw in draws:
            data = {
                "period": draw.get('period'),
                "date": draw.get('date'),
                "numbers": draw['numbers'],
                "special": draw.get('special'),
                "sum_value": draw['sum']
            }
            table.insert(data).execute()
        
        return True
    except Exception as e:
        st.error(f"保存到Supabase失败: {e}")
        return False

def load_draws_from_supabase():
    """从Supabase加载开奖数据"""
    supabase = init_supabase()
    if supabase is None:
        return None
    
    try:
        response = supabase.schema('marksix_schema').table('marksix_draws').select("*").order("period", desc=False).execute()
        draws = []
        for row in response.data:
            draws.append({
                'period': row.get('period'),
                'date': row.get('date'),
                'numbers': row['numbers'],
                'special': row.get('special'),
                'sum': row['sum_value']
            })
        return draws
    except Exception as e:
        st.error(f"从Supabase加载数据失败: {e}")
        return None

# ==================== 核心函数 ====================

def parse_pasted_data(text):
    """解析粘贴的数据文本"""
    lines = text.strip().split('\n')
    draws = []
    
    for line in lines:
        if not line.strip():
            continue
        
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
                        'period': int(parts[0]) if parts[0].isdigit() else parts[0],
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
                            'period': int(row.get('期次', idx+1)) if str(row.get('期次', idx+1)).isdigit() else idx+1,
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

def get_target_sum_by_numbers_count(num_count):
    """根据号码个数返回目标和值"""
    # 基于 (1+49)/2 = 25
    return 25 * num_count

def convert_6sum_to_7sum(sum_6):
    """将6码和值转换为7码和值（按比例）"""
    # 6码理论均值150，7码理论均值175，比例 = 175/150 = 7/6
    return int(sum_6 * 7 / 6)

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

def generate_combination(scores, num_count, target_sum=None, tolerance=15, require_pattern=True):
    """生成符合条件的一组号码
    
    Args:
        scores: 号码得分字典
        num_count: 需要生成的号码个数
        target_sum: 目标和值（None表示不约束）
        tolerance: 和值容差
        require_pattern: 是否要求包含连号或跳号
    """
    min_sum = target_sum - tolerance if target_sum is not None else 0
    max_sum = target_sum + tolerance if target_sum is not None else 500
    
    sorted_numbers = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    hot_numbers = sorted_numbers[:15]
    cold_numbers = sorted_numbers[-10:]
    
    max_attempts = 50000
    for _ in range(max_attempts):
        selected = set()
        
        # 选2-3个热码
        num_hot = min(random.randint(2, 3), num_count)
        hot_pool = [n for n in hot_numbers if n not in selected]
        if len(hot_pool) >= num_hot:
            selected.update(random.sample(hot_pool, num_hot))
        
        # 从剩余号码中选满
        remaining = [n for n in range(1, 50) if n not in selected and n not in cold_numbers[:5]]
        if len(remaining) < num_count - len(selected):
            continue
        selected.update(random.sample(remaining, num_count - len(selected)))
        
        nums = sorted(selected)
        total = sum(nums)
        
        # 检查和值约束
        if target_sum is not None:
            if not (min_sum <= total <= max_sum):
                continue
        
        # 检查连号/跳号
        if require_pattern:
            if has_consecutive_or_jump(nums):
                return nums, total
        else:
            return nums, total
    
    # 降级
    for _ in range(10000):
        nums = sorted(random.sample(range(1, 50), num_count))
        total = sum(nums)
        if target_sum is not None:
            if min_sum <= total <= max_sum:
                return nums, total
        else:
            return nums, total
    
    return sorted(random.sample(range(1, 50), num_count)), sum(sorted(random.sample(range(1, 50), num_count)))

def predict_trend_7code(draws, window=5):
    """根据最近window期的6码和值预测下一期7码趋势"""
    if len(draws) < window:
        return "中"
    
    recent_sums_6 = [draw['sum'] for draw in draws[-window:]]
    recent_sums_7 = [convert_6sum_to_7sum(s) for s in recent_sums_6]
    avg_sum = np.mean(recent_sums_7)
    
    if avg_sum > 185:
        return "小"
    elif avg_sum < 165:
        return "大"
    else:
        return "中"

def get_trend_target_sum(trend, num_count):
    """根据趋势返回目标值"""
    base_sum = get_target_sum_by_numbers_count(num_count)
    if trend == "小":
        return base_sum - 15
    elif trend == "大":
        return base_sum + 15
    else:
        return base_sum

def set_random_seed(seed_input):
    """设置随机种子"""
    if seed_input is not None:
        try:
            random.seed(seed_input)
            np.random.seed(seed_input)
        except (ValueError, TypeError):
            random.seed(42)
            np.random.seed(42)
    else:
        # 完全随机
        random.seed()
        np.random.seed()

def generate_bets_by_strategy(draws, scores, num_bets, strategy, num_count, require_pattern, trend_window, seed_input):
    """根据策略生成投注"""
    set_random_seed(seed_input)
    
    bets = []
    base_target = get_target_sum_by_numbers_count(num_count)
    
    if strategy == "和值大中小":
        if num_bets >= 1:
            nums, total = generate_combination(scores, num_count, base_target - 15, 15, require_pattern)
            bets.append({'numbers': nums, 'sum': total, 'target': f'小和值({base_target-15})', 'deviation': total - base_target})
        if num_bets >= 2:
            nums, total = generate_combination(scores, num_count, base_target, 15, require_pattern)
            bets.append({'numbers': nums, 'sum': total, 'target': f'中和值({base_target})', 'deviation': total - base_target})
        if num_bets >= 3:
            nums, total = generate_combination(scores, num_count, base_target + 15, 15, require_pattern)
            bets.append({'numbers': nums, 'sum': total, 'target': f'大和值({base_target+15})', 'deviation': total - base_target})
        for i in range(3, num_bets):
            nums, total = generate_combination(scores, num_count, base_target, 15, require_pattern)
            bets.append({'numbers': nums, 'sum': total, 'target': f'中和值({base_target}) 补充{i-2}', 'deviation': total - base_target})
    
    elif strategy == "和值趋势预测":
        trend = predict_trend_7code(draws, window=trend_window)
        trend_target = get_trend_target_sum(trend, num_count)
        for i in range(num_bets):
            offset = random.randint(-5, 5)
            target = trend_target + offset
            target = max(25 * num_count - 30, min(25 * num_count + 30, target))
            nums, total = generate_combination(scores, num_count, target, 15, require_pattern)
            bets.append({'numbers': nums, 'sum': total, 'target': f'{trend}和值趋势(目标{target})', 'deviation': total - base_target})
    
    else:  # 混合策略
        half = max(1, num_bets // 2)
        if half >= 1:
            nums, total = generate_combination(scores, num_count, base_target - 15, 15, require_pattern)
            bets.append({'numbers': nums, 'sum': total, 'target': f'小和值({base_target-15})', 'deviation': total - base_target})
        if half >= 2:
            nums, total = generate_combination(scores, num_count, base_target, 15, require_pattern)
            bets.append({'numbers': nums, 'sum': total, 'target': f'中和值({base_target})', 'deviation': total - base_target})
        if half >= 3:
            nums, total = generate_combination(scores, num_count, base_target + 15, 15, require_pattern)
            bets.append({'numbers': nums, 'sum': total, 'target': f'大和值({base_target+15})', 'deviation': total - base_target})
        trend = predict_trend_7code(draws, window=trend_window)
        trend_target = get_trend_target_sum(trend, num_count)
        for i in range(num_bets - half):
            offset = random.randint(-5, 5)
            target = trend_target + offset
            target = max(25 * num_count - 30, min(25 * num_count + 30, target))
            nums, total = generate_combination(scores, num_count, target, 15, require_pattern)
            bets.append({'numbers': nums, 'sum': total, 'target': f'{trend}和值趋势(目标{target})', 'deviation': total - base_target})
    
    return bets

def calculate_prize(match_count, special_match):
    """根据匹配数计算奖金（6个正码）"""
    if match_count == 6:
        return "第1组 (45%基金)", 0
    elif match_count == 5 and special_match:
        return "第2组 (15%基金)", 0
    elif match_count == 5:
        return "第3组 (40%基金)", 0
    elif match_count == 4 and special_match:
        return "第4组 ($9,600)", 9600
    elif match_count == 4:
        return "第5组 ($640)", 640
    elif match_count == 3 and special_match:
        return "第6组 ($320)", 320
    elif match_count == 3:
        return "第7组 ($40)", 40
    else:
        return "无中奖", 0

def backtest_strategy(draws, num_bets_per_draw, strategy, num_count, require_pattern, trend_window, analysis_periods, test_periods, seed_input):
    """回测策略 - 只测试最后N期"""
    set_random_seed(seed_input)
    
    if len(draws) < test_periods + analysis_periods:
        return None, f"数据不足：需要至少 {test_periods + analysis_periods} 期数据"
    
    results = []
    test_start = len(draws) - test_periods
    
    for i in range(test_start, len(draws)):
        train_draws = draws[:i]
        test_draw = draws[i]
        
        train_scores, _, _, _ = calculate_scores(train_draws, window_total=analysis_periods)
        
        bets = generate_bets_by_strategy(
            train_draws, train_scores, num_bets_per_draw, strategy,
            num_count, require_pattern, trend_window, None
        )
        
        best_match = 0
        best_special_match = False
        best_prize = "无中奖"
        best_amount = 0
        
        for bet in bets:
            # 只匹配正码（前6个）
            match_count = len(set(bet['numbers'][:6]) & set(test_draw['numbers']))
            special_match = test_draw.get('special') in bet['numbers'] if test_draw.get('special') else False
            
            if match_count > best_match or (match_count == best_match and special_match):
                best_match = match_count
                best_special_match = special_match
                best_prize, best_amount = calculate_prize(match_count, special_match)
        
        results.append({
            '期次': test_draw.get('period', i+1),
            '日期': test_draw.get('date', ''),
            '真实号码': str(test_draw['numbers']),
            '真实和值': test_draw['sum'],
            '最佳匹配数': best_match,
            '特别号匹配': best_special_match,
            '中奖等级': best_prize,
            '奖金': best_amount
        })
    
    return pd.DataFrame(results), None

def display_backtest_results(results_df, backtest_bets):
    """显示回测结果"""
    st.markdown("### 📈 回测结果统计")
    
    stat_col1, stat_col2, stat_col3, stat_col4, stat_col5 = st.columns(5)
    
    total_draws_count = len(results_df)
    winning_draws_count = results_df[results_df['中奖等级'] != '无中奖'].shape[0]
    avg_match_val = results_df['最佳匹配数'].mean()
    
    total_prize = results_df['奖金'].sum()
    total_cost = len(results_df) * backtest_bets * 10
    
    with stat_col1:
        st.metric("测试期数", total_draws_count)
    with stat_col2:
        st.metric("中奖期数", winning_draws_count)
    with stat_col3:
        st.metric("中奖率", f"{winning_draws_count/total_draws_count*100:.1f}%")
    with stat_col4:
        st.metric("平均匹配数", f"{avg_match_val:.2f}")
    with stat_col5:
        roi_val = ((total_prize - total_cost) / total_cost) * 100 if total_cost > 0 else 0
        st.metric("投资回报率(ROI)", f"{roi_val:+.1f}%")
    
    st.markdown(f"""
    **💰 资金统计**
    - 总投入: **${total_cost}**
    - 总奖金: **${total_prize}**
    - 净收益: **${total_prize - total_cost}**
    """)
    
    match_dist = results_df['最佳匹配数'].value_counts().sort_index()
    fig_match = px.bar(
        x=match_dist.index, y=match_dist.values,
        title='每期最佳匹配数分布',
        labels={'x': '匹配号码数', 'y': '期数'}
    )
    st.plotly_chart(fig_match, use_container_width=True)
    
    with st.expander("📋 详细回测结果"):
        st.dataframe(results_df, use_container_width=True)

# ==================== 管理员验证函数 ====================
def check_password(password):
    """验证管理员密码"""
    return hmac.compare_digest(password, "Ku_product$2026")

def admin_login():
    """管理员登录界面"""
    with st.form("admin_login_form"):
        username = st.text_input("用户名")
        password = st.text_input("密码", type="password")
        submitted = st.form_submit_button("登录")
        
        if submitted:
            if username == "Laurence_ku" and check_password(password):
                st.session_state['admin_logged_in'] = True
                st.session_state['show_admin'] = False
                st.success("登录成功！")
                st.rerun()
            else:
                st.error("用户名或密码错误")

def admin_logout():
    """管理员登出"""
    if st.button("退出登录", key="logout_btn"):
        st.session_state['admin_logged_in'] = False
        st.session_state['show_admin'] = False
        st.rerun()

# ==================== 管理员页面 ====================
def show_admin_page():
    """显示管理员页面"""
    with st.expander("🔧 管理员控制台", expanded=True):
        st.subheader("📁 历史数据管理")
        
        current_draws = load_draws_from_supabase()
        if current_draws:
            st.success(f"✅ 当前云端有 {len(current_draws)} 期数据")
            st.info(f"📊 数据范围: {current_draws[0].get('period')} 到 {current_draws[-1].get('period')}")
        else:
            st.info("📭 云端暂无数据")
        
        st.markdown("---")
        
        admin_input_method = st.radio(
            "选择数据输入方式",
            ["粘贴数据", "上传Excel文件"],
            horizontal=True,
            key="admin_input"
        )
        
        parsed_draws = None
        
        if admin_input_method == "粘贴数据":
            st.markdown("""
            **数据格式**: 每期一行，用制表符或逗号分隔
            期次 日期 B1 B2 B3 B4 B5 B6 B7
            示例: 26045 2026-04-25 4 16 21 36 42 46 9
            """)
            
            admin_pasted = st.text_area(
                "粘贴历史数据",
                height=300,
                key="admin_pasted",
                help="支持制表符、逗号或空格分隔"
            )
            
            if admin_pasted:
                if st.button("预览数据", key="preview_pasted"):
                    parsed_draws = parse_pasted_data(admin_pasted)
                    if parsed_draws:
                        st.session_state['preview_draws'] = parsed_draws
                        st.success(f"成功解析 {len(parsed_draws)} 期数据")
                        st.dataframe(pd.DataFrame(parsed_draws[-20:]), use_container_width=True)
                    else:
                        st.error("数据解析失败")
                
                if st.session_state.get('preview_draws') is not None:
                    parsed_draws = st.session_state['preview_draws']
        
        else:
            admin_file = st.file_uploader(
                "上传Excel文件",
                type=['xlsx', 'xls'],
                key="admin_file"
            )
            
            if admin_file:
                if st.button("预览数据", key="preview_excel"):
                    parsed_draws = parse_excel_file(admin_file)
                    if parsed_draws:
                        st.session_state['preview_draws'] = parsed_draws
                        st.success(f"成功解析 {len(parsed_draws)} 期数据")
                        st.dataframe(pd.DataFrame(parsed_draws[-20:]), use_container_width=True)
                    else:
                        st.error("数据解析失败")
                
                if st.session_state.get('preview_draws') is not None:
                    parsed_draws = st.session_state['preview_draws']
        
        if parsed_draws:
            st.markdown("---")
            st.subheader("💾 保存到云端")
            
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("☁️ 保存到Supabase", type="primary", key="save_to_supabase"):
                    with st.spinner("正在保存..."):
                        if save_draws_to_supabase(parsed_draws):
                            st.success(f"成功保存 {len(parsed_draws)} 期数据到Supabase！")
                            st.session_state['preview_draws'] = None
                            st.balloons()
                            st.rerun()
                        else:
                            st.error("保存失败")
            
            with col2:
                if st.button("❌ 取消", key="cancel_save"):
                    st.session_state['preview_draws'] = None
                    st.rerun()
        
        st.markdown("---")
        
        # ==================== 策略回测 ====================
        st.subheader("📊 策略回测")
        
        draws = load_draws_from_supabase()
        
        if draws is None or len(draws) == 0:
            st.warning("请先保存数据到Supabase，再进行回测")
        else:
            col1, col2, col3, col4, col5, col6 = st.columns(6)
            
            with col1:
                backtest_bets = st.number_input(
                    "回测注数",
                    min_value=1,
                    max_value=10,
                    value=4,
                    step=1,
                    key="backtest_bets"
                )
            
            with col2:
                backtest_strategy = st.selectbox(
                    "回测策略",
                    ["和值大中小", "和值趋势预测", "混合策略"],
                    key="backtest_strategy"
                )
            
            with col3:
                backtest_num_count = st.selectbox(
                    "每注号码数",
                    [6, 7, 8, 9, 10],
                    index=1,
                    key="backtest_num_count",
                    help="6=正码, 7=正码+特码"
                )
            
            with col4:
                backtest_pattern = st.selectbox(
                    "连号/跳号",
                    ["是", "否"],
                    index=0,
                    key="backtest_pattern",
                    help="是否强制包含连号或跳号"
                )
            
            with col5:
                backtest_trend_window = st.number_input(
                    "趋势窗口",
                    min_value=3,
                    max_value=20,
                    value=5,
                    step=1,
                    key="backtest_trend_window",
                    help="和值预测使用的窗口期数"
                )
            
            with col6:
                backtest_periods = st.number_input(
                    "测试期数",
                    min_value=5,
                    max_value=100,
                    value=20,
                    step=5,
                    key="backtest_periods"
                )
            
            compare_seeds = st.button("🔬 对比多个Random Seed", type="secondary", key="compare_seeds")
            run_backtest = st.button("▶️ 运行回测", type="secondary", key="run_backtest")
            
            if run_backtest:
                with st.spinner("正在运行回测..."):
                    results_df, error = backtest_strategy(
                        draws, backtest_bets, backtest_strategy, backtest_num_count,
                        backtest_pattern == "是", backtest_trend_window,
                        100, backtest_periods, 42
                    )
                    
                    if error:
                        st.warning(error)
                    elif results_df is not None and len(results_df) > 0:
                        display_backtest_results(results_df, backtest_bets)
            
            if compare_seeds:
                st.markdown("### 🔬 不同 Random Seed 对比测试")
                seeds_to_test = [1, 3, 5, 7, 9]
                comparison_results = []
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for idx, seed in enumerate(seeds_to_test):
                    status_text.text(f"正在测试 Seed: {seed}")
                    
                    results_df, error = backtest_strategy(
                        draws, backtest_bets, backtest_strategy, backtest_num_count,
                        backtest_pattern == "是", backtest_trend_window,
                        100, backtest_periods, seed
                    )
                    
                    if results_df is not None and len(results_df) > 0:
                        total_draws_count = len(results_df)
                        winning_draws_count = results_df[results_df['中奖等级'] != '无中奖'].shape[0]
                        total_prize = results_df['奖金'].sum()
                        total_cost = total_draws_count * backtest_bets * 10
                        roi_val = ((total_prize - total_cost) / total_cost) * 100 if total_cost > 0 else 0
                        
                        comparison_results.append({
                            'Random Seed': seed,
                            '测试期数': total_draws_count,
                            '中奖期数': winning_draws_count,
                            '中奖率': f"{winning_draws_count/total_draws_count*100:.1f}%",
                            '总投入': f"${total_cost}",
                            '总奖金': f"${total_prize}",
                            'ROI': f"{roi_val:+.1f}%"
                        })
                    
                    progress_bar.progress((idx + 1) / len(seeds_to_test))
                
                status_text.text("对比完成！")
                
                if comparison_results:
                    comparison_df = pd.DataFrame(comparison_results)
                    st.dataframe(comparison_df, use_container_width=True)
                    
                    win_rates = []
                    for r in comparison_results:
                        rate = float(r['中奖率'].replace('%', ''))
                        win_rates.append(rate)
                    
                    st.markdown(f"""
                    **📊 统计分析**
                    - 平均中奖率: **{np.mean(win_rates):.1f}%**
                    - 中奖率标准差: **{np.std(win_rates):.2f}%**
                    - 最高中奖率: **{max(win_rates):.1f}%**
                    - 最低中奖率: **{min(win_rates):.1f}%**
                    """)
                    
                    if np.std(win_rates) < 3:
                        st.success("✅ 结论: Random Seed 对中奖率影响很小 (标准差 < 3%)")
                    else:
                        st.warning("⚠️ 结论: Random Seed 对中奖率有较大影响，建议多次运行取平均")
                else:
                    st.warning("回测数据不足")

# ==================== 初始化session state ====================
if 'admin_logged_in' not in st.session_state:
    st.session_state['admin_logged_in'] = False
if 'show_admin' not in st.session_state:
    st.session_state['show_admin'] = False
if 'preview_draws' not in st.session_state:
    st.session_state['preview_draws'] = None

# ==================== 右上角齿轮图标 ====================
col_title, col_settings = st.columns([0.95, 0.05])
with col_settings:
    if st.button("⚙️", key="settings_icon", help="管理员设置"):
        st.session_state['show_admin'] = not st.session_state.get('show_admin', False)

# 显示管理员页面
if st.session_state.get('show_admin', False):
    if not st.session_state['admin_logged_in']:
        admin_login()
    else:
        show_admin_page()
        admin_logout()

# ==================== 理论介绍（左侧边栏） ====================
with st.sidebar:
    st.title("🎰 六合彩AI分析工具")
    st.markdown("---")
    
    with st.expander("📖 中央趋向定理", expanded=False):
        st.markdown("""
        - 从49个球抽取7个球，和值呈正态分布
        - 理论和值（7码）: (1+49)/2 * 7 = 175
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
        | 第1组 | 6 | 45%基金 |
        | 第2组 | 5+特 | 15%基金 |
        | 第3组 | 5 | 40%基金 |
        | 第4组 | 4+特 | $9,600 |
        | 第5组 | 4 | $640 |
        | 第6组 | 3+特 | $320 |
        | 第7组 | 3 | $40 |
        """)
    
    st.markdown("---")
    st.caption("DFSS智能选号工具 v1.0")

# ==================== 主页面 ====================

st.title("🎯 六合彩AI智能选号工具")

# 从 Supabase 加载数据
@st.cache_data(ttl=60, show_spinner="从云端加载数据...")
def get_draws_from_cloud():
    return load_draws_from_supabase()

draws = get_draws_from_cloud()

if draws is None or len(draws) == 0:
    st.info("👈 请点击右上角齿轮图标，进入管理员页面导入历史数据")
    st.stop()

# ==================== 显示最新期数和数据概览 ====================
st.subheader("📊 数据概览")

latest_draw = draws[-1]
latest_period = latest_draw.get('period', 'N/A')
latest_date = latest_draw.get('date', 'N/A')

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("最新期次", latest_period)
with col2:
    st.metric("最新日期", latest_date)
with col3:
    st.metric("数据总量", f"{len(draws)} 期")

# ==================== 冷热码分析 ====================
st.subheader("🔥 冷热码分析")

col1, col2 = st.columns(2)

with col1:
    analysis_periods = st.number_input(
        "分析期数",
        min_value=10,
        max_value=min(500, len(draws)),
        value=min(100, len(draws)),
        step=10,
        help="使用最近N期数据计算冷热码"
    )

scores, freq, short_freq, absence = calculate_scores(draws, window_total=analysis_periods)

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**🔥 热门号码 (Top 10)**")
    hot_df = pd.DataFrame([
        {'号码': num, '得分': f"{scores[num]:.2f}", '总次数': freq[num], '缺席次数': absence[num]}
        for num in sorted(scores, key=scores.get, reverse=True)[:10]
    ])
    st.dataframe(hot_df, use_container_width=True)

with col2:
    st.markdown("**❄️ 冷门号码 (Bottom 10)**")
    cold_df = pd.DataFrame([
        {'号码': num, '得分': f"{scores[num]:.2f}", '总次数': freq[num], '缺席次数': absence[num]}
        for num in sorted(scores, key=scores.get)[:10]
    ])
    st.dataframe(cold_df, use_container_width=True)

with col3:
    st.markdown("**📈 近期活跃**")
    recent_active = [num for num in range(1, 50) if any(num in draw['numbers'] for draw in draws[-10:])]
    st.write(f"近10期出现过的号码: **{len(recent_active)}个**")
    st.write(sorted(recent_active)[:15], "...")
    if len(recent_active) > 15:
        st.write(f"... 共{len(recent_active)}个")

# ==================== 和值趋势分析（以7码显示） ====================
st.subheader("📈 和值趋势分析（7个号码）")

show_periods = st.slider(
    "显示最近期数",
    min_value=10,
    max_value=min(200, len(draws)),
    value=min(100, len(draws)),
    step=10
)

# 将6码和值转换为7码和值
sum_7_values = [convert_6sum_to_7sum(draw['sum']) for draw in draws[-show_periods:]]

sum_df = pd.DataFrame([
    {'期次': i+1, '和值(7码)': val}
    for i, val in enumerate(sum_7_values)
])

fig = px.line(sum_df, x='期次', y='和值(7码)', title=f'最近{show_periods}期和值走势 (7个号码 - 按比例转换)')
fig.add_hline(y=175, line_dash="dash", line_color="red", annotation_text="理论均值(175)")
fig.add_hrect(y0=140, y1=210, line_width=0, fillcolor="green", opacity=0.1, annotation_text="约68%区间")
st.plotly_chart(fig, use_container_width=True)

sum_stats = pd.DataFrame(sum_7_values, columns=['和值(7码)'])
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("平均和值", f"{sum_stats['和值(7码)'].mean():.1f}")
with col2:
    st.metric("最大和值", f"{sum_stats['和值(7码)'].max()}")
with col3:
    st.metric("最小和值", f"{sum_stats['和值(7码)'].min()}")
with col4:
    st.metric("标准差", f"{sum_stats['和值(7码)'].std():.1f}")

# 当前趋势预测（基于7码）
if len(draws) >= 5:
    recent_sums_7 = [convert_6sum_to_7sum(draw['sum']) for draw in draws[-5:]]
    avg_sum = np.mean(recent_sums_7)
    if avg_sum > 185:
        trend_desc = "📈 偏大 → 建议关注小和值 (160)"
    elif avg_sum < 165:
        trend_desc = "📉 偏小 → 建议关注大和值 (190)"
    else:
        trend_desc = "⚖️ 正常 → 建议关注中和值 (175)"
    st.info(f"**当前和值趋势分析**: 最近5期平均和值(7码) = {avg_sum:.1f} | {trend_desc}")

# ==================== 智能投注生成 ====================
st.subheader("🎲 智能投注生成")

# 计算下一期期次
next_period = latest_period + 1 if isinstance(latest_period, int) else "N/A"

st.info(f"🎯 **预测下一期**: {next_period}")

# 用户输入参数
col1, col2, col3, col4 = st.columns(4)

with col1:
    num_bets = st.number_input(
        "购买注数",
        min_value=1,
        max_value=10,
        value=4,
        step=1,
        help="每次购买多少注"
    )

with col2:
    num_count = st.selectbox(
        "每注号码个数",
        [6, 7, 8, 9, 10],
        index=1,
        help="6=6个正码, 7=6正码+1特码"
    )

with col3:
    strategy = st.selectbox(
        "购买策略",
        ["和值大中小", "和值趋势预测", "混合策略"],
        help="和值大中小: 覆盖小/中/大和值区间"
    )

with col4:
    require_pattern = st.selectbox(
        "连号/跳号要求",
        ["是", "否"],
        index=0,
        help="是否要求每注至少包含一对连号或跳号"
    )

col1, col2, col3 = st.columns(3)

with col1:
    trend_window = st.number_input(
        "趋势预测窗口",
        min_value=3,
        max_value=20,
        value=5,
        step=1,
        help="和值趋势预测使用的最近期数"
    )

with col2:
    # 开奖日期选择器
    selected_date = st.date_input(
        "开奖日期",
        value=datetime.now(),
        help="用于生成Random Seed的开奖日期"
    )
    
    use_dynamic_seed = st.selectbox(
        "Random Seed模式",
        ["使用选定日期+21:30", "固定种子1", "固定种子3", "固定种子5", "固定种子7", "固定种子9", "完全随机"],
        index=0,
        help="影响随机数生成"
    )

with col3:
    use_analysis_periods = st.number_input(
        "分析期数",
        min_value=10,
        max_value=min(500, len(draws)),
        value=min(100, len(draws)),
        step=10,
        key="gen_periods",
        help="使用最近N期数据计算冷热码"
    )

# 生成随机种子
if use_dynamic_seed == "使用选定日期+21:30":
    seed_value = int(selected_date.strftime("%Y%m%d") + "2130")
    random_seed = seed_value
    seed_display = f"{selected_date.strftime('%Y-%m-%d')} 21:30"
elif use_dynamic_seed == "完全随机":
    random_seed = None
    seed_display = "完全随机"
else:
    random_seed = int(use_dynamic_seed.split("种子")[1])
    seed_display = use_dynamic_seed

if st.button("🚀 生成智能投注", type="primary"):
    gen_scores, _, _, _ = calculate_scores(draws, window_total=use_analysis_periods)
    
    bets = generate_bets_by_strategy(
        draws, gen_scores, num_bets, strategy,
        num_count, require_pattern == "是", trend_window, random_seed
    )
    
    st.markdown("### 📝 推荐投注组合")
    
    st.markdown(f"""
    **⚙️ 当前设置**
    - Random Seed: `{seed_display}`
    - 连号/跳号要求: {require_pattern}
    - 趋势窗口: {trend_window}期
    """)
    
    # 用表格显示
    bets_data = []
    base_target = get_target_sum_by_numbers_count(num_count)
    for i, bet in enumerate(bets, 1):
        # 格式化号码显示（特码用括号标注）
        if len(bet['numbers']) == 7:
            numbers_display = f"{bet['numbers'][:6]} + [{bet['numbers'][6]}]"
        else:
            numbers_display = str(bet['numbers'])
        
        bets_data.append({
            '注数': i,
            '推荐号码': numbers_display,
            '和值': bet['sum'],
            '目标策略': bet['target'],
            '偏差': f"{bet['deviation']:+d}" if bet['deviation'] != 0 else "0",
            '连号/跳号': "✅" if has_consecutive_or_jump(bet['numbers']) else "❌"
        })
    
    bets_df = pd.DataFrame(bets_data)
    st.dataframe(bets_df, use_container_width=True, hide_index=True)
    
    # 显示预测信息
    st.info(f"""
    📊 **预测信息**
    - 使用最近 {use_analysis_periods} 期数据进行分析
    - 当前策略: {strategy}
    - 共生成 {num_bets} 注推荐号码
    - 每注 {num_count} 个号码
    - 理论期望和值 (基于中央趋向定理): {get_target_sum_by_numbers_count(num_count)}
    """)
    
    # 显示小提示
    if num_count == 7:
        st.caption("💡 提示: 7个号码包含6个正码和1个特码，特码已用括号标注")

# 页脚
st.markdown("---")
st.caption("⚠️ 本工具仅供学术研究和娱乐参考。六合彩本质上是一种随机游戏，长期期望值为负，请理性投注。")
