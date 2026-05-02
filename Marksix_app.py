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

# 自定义CSS让所有表格居中
st.markdown("""
<style>
    .stDataFrame {
        text-align: center;
    }
    .stDataFrame table {
        text-align: center;
        width: 100%;
    }
    .stDataFrame th {
        text-align: center !important;
    }
    .stDataFrame td {
        text-align: center !important;
    }
    .stMetric {
        text-align: center;
    }
    .stNumberInput input {
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ==================== Supabase 初始化 ====================
def init_supabase():
    try:
        supabase_url = st.secrets["SUPABASE_URL"]
        supabase_key = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
        return create_client(supabase_url, supabase_key)
    except Exception as e:
        st.error(f"Supabase连接失败: {e}")
        return None

def save_draws_to_supabase(draws):
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

# ==================== 分区函数 ====================
def get_zone(num):
    """获取号码所在分区 (1-7区，每区7个号码)"""
    return (num - 1) // 7 + 1

def get_zone_numbers(zone):
    """获取分区内的所有号码"""
    start = (zone - 1) * 7 + 1
    end = start + 6
    return list(range(start, end + 1))

def calculate_zone_heat(draws, last_n=20):
    """计算各分区的热度统计"""
    zone_hits = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0}
    zone_trend = {1: [], 2: [], 3: [], 4: [], 5: [], 6: [], 7: []}
    
    for idx, draw in enumerate(draws[-last_n:]):
        for num in draw['numbers']:
            zone = get_zone(num)
            zone_hits[zone] += 1
            zone_trend[zone].append(idx)
    
    # 计算每个分区的热度得分 (出现次数 + 近期趋势权重)
    zone_scores = {}
    for zone in range(1, 8):
        hits = zone_hits[zone]
        # 近期出现次数越近权重越高
        recent_weight = 0
        for pos in zone_trend[zone][-5:]:  # 最近5期
            recent_weight += (5 - (last_n - pos)) if (last_n - pos) < 5 else 0
        zone_scores[zone] = hits * 1.0 + recent_weight * 0.5
    
    return zone_scores, zone_hits

def get_hot_zones(zone_scores, num_hot_zones=3):
    """获取最热的分区"""
    sorted_zones = sorted(zone_scores.items(), key=lambda x: x[1], reverse=True)
    return [zone for zone, score in sorted_zones[:num_hot_zones]]

# ==================== 核心函数 ====================

def parse_pasted_data(text):
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

def parse_multi_draws_for_checking(text, max_draws=5):
    lines = text.strip().split('\n')
    draws = []
    for line in lines:
        if len(draws) >= max_draws:
            break
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
                        'period': parts[0],
                        'numbers': sorted(nums[:6]),
                        'special': nums[6]
                    })
            except (ValueError, IndexError):
                continue
    return draws

def parse_excel_file(uploaded_file):
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
    return 25 * num_count

def convert_6sum_to_7sum(sum_6):
    return int(sum_6 * 7 / 6)

def calculate_scores(draws, window_total=100, window_short=20, window_recent=10):
    """基础冷热码评分（4因子）"""
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
        z_absence = (absence_mean - absence[i]) / absence_std if absence_std > 0 else 0
        z_short = (short_freq[i] - short_mean) / short_std if short_std > 0 else 0
        recent_active = 1 if i in recent_numbers else -1
        
        score = 0.3 * z_freq + 0.3 * z_absence + 0.2 * z_short + 0.2 * recent_active
        scores[i] = score
    
    return scores, freq, short_freq, absence

def calculate_enhanced_scores(draws, window_total=100, window_short=20, window_recent=10):
    """
    增强版评分模型
    整合：冷热码评分 + 上期重复加分 + 隔期加分 + 分区热度加分
    """
    # 1. 基础冷热码评分
    base_scores, freq, short_freq, absence = calculate_scores(draws, window_total, window_short, window_recent)
    
    # 2. 获取上期数据
    last_draw = draws[-1]
    last_numbers = last_draw['numbers']
    last_special = last_draw.get('special')
    last_draw_all = last_numbers + [last_special]
    
    # 3. 获取分区热度
    zone_scores, _ = calculate_zone_heat(draws, last_n=20)
    hot_zones = get_hot_zones(zone_scores, num_hot_zones=3)
    
    # 4. 计算额外加分
    repeat_boost = {}
    for num in range(1, 50):
        boost = 0.0
        
        # 上期重复加分（最高权重）
        if num in last_draw_all:
            boost += 2.0
        
        # 隔期加分（上上期出现，上期未出现）
        if len(draws) >= 2:
            prev_draw = draws[-2]
            prev_numbers = prev_draw['numbers'] + [prev_draw.get('special')]
            if num in prev_numbers and num not in last_draw_all:
                boost += 1.0
        
        # 前3期出现2次以上加分
        if len(draws) >= 3:
            last_3_draws = draws[-3:]
            count_in_last_3 = 0
            for d in last_3_draws:
                if num in d['numbers'] or num == d.get('special'):
                    count_in_last_3 += 1
            if count_in_last_3 >= 2 and num not in last_draw_all:
                boost += 0.8
        
        # 前5期出现3次以上加分
        if len(draws) >= 5:
            last_5_draws = draws[-5:]
            count_in_last_5 = 0
            for d in last_5_draws:
                if num in d['numbers'] or num == d.get('special'):
                    count_in_last_5 += 1
            if count_in_last_5 >= 3:
                boost += 0.5
        
        # 分区热度加分（热区内的号码加分）
        num_zone = get_zone(num)
        if num_zone in hot_zones:
            boost += 1.2
        
        repeat_boost[num] = boost
    
    # 综合得分 = 基础分 + 额外加分
    enhanced_scores = {}
    for num in range(1, 50):
        enhanced_scores[num] = base_scores[num] + repeat_boost[num]
    
    return enhanced_scores, repeat_boost, hot_zones

def has_consecutive_or_jump(nums):
    nums = sorted(nums)
    for i in range(len(nums)-1):
        diff = nums[i+1] - nums[i]
        if diff == 1 or diff == 2:
            return True
    return False

def get_sum_range_by_bets(num_bets):
    """根据注数动态返回和值偏移量"""
    if num_bets <= 5:
        return 15
    elif num_bets <= 10:
        return 20
    elif num_bets <= 20:
        return 25
    else:
        return 30

def generate_combination(scores, num_count, target_sum=None, tolerance=15, require_pattern=True, 
                         last_draw_numbers=None, last_draw_special=None, hot_zones=None):
    """
    增强版号码生成
    整合：热码优先 + 上期重复 + 分区筛选 + 和值约束 + 连号/跳号
    """
    min_sum = target_sum - tolerance if target_sum is not None else 0
    max_sum = target_sum + tolerance if target_sum is not None else 500
    
    # 获取上期号码列表
    last_draw_all = []
    if last_draw_numbers and last_draw_special:
        last_draw_all = last_draw_numbers + [last_draw_special]
    
    # 按得分排序
    sorted_numbers = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    
    # 上期号码优先提到最前面
    if last_draw_all:
        prioritized = last_draw_all + [n for n in sorted_numbers if n not in last_draw_all]
    else:
        prioritized = sorted_numbers
    
    hot_numbers = prioritized[:20]  # 扩大到20个热码
    cold_numbers = prioritized[-10:]
    
    # 获取热区号码池
    hot_zone_numbers = []
    if hot_zones:
        for zone in hot_zones:
            hot_zone_numbers.extend(get_zone_numbers(zone))
    
    max_attempts = 50000
    for _ in range(max_attempts):
        selected = set()
        
        # 1. 强制包含1-2个上期重复号码
        if last_draw_all:
            num_prev = random.randint(1, 2)
            prev_pool = [n for n in last_draw_all if n not in selected]
            if len(prev_pool) >= num_prev:
                selected.update(random.sample(prev_pool, num_prev))
        
        # 2. 再从热区中选1-2个
        remaining_hot_zone = [n for n in hot_zone_numbers if n not in selected and n in hot_numbers]
        num_zone = min(random.randint(1, 2), num_count - len(selected))
        if len(remaining_hot_zone) >= num_zone:
            selected.update(random.sample(remaining_hot_zone, num_zone))
        
        # 3. 再从热码中补充
        remaining_hot = [n for n in hot_numbers if n not in selected]
        num_hot = min(random.randint(1, 2), num_count - len(selected))
        if len(remaining_hot) >= num_hot:
            selected.update(random.sample(remaining_hot, num_hot))
        
        # 4. 从剩余号码中选满（避开前5冷码）
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
    
    # 降级处理
    for _ in range(10000):
        nums = sorted(random.sample(range(1, 50), num_count))
        total = sum(nums)
        if target_sum is not None:
            if not (min_sum <= total <= max_sum):
                continue
        if require_pattern:
            if has_consecutive_or_jump(nums):
                return nums, total
        else:
            return nums, total
    
    return sorted(random.sample(range(1, 50), num_count)), sum(sorted(random.sample(range(1, 50), num_count)))

def predict_trend_7code(draws, window=5):
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
    base_sum = get_target_sum_by_numbers_count(num_count)
    if trend == "小":
        return base_sum - 15
    elif trend == "大":
        return base_sum + 15
    else:
        return base_sum

def set_random_seed(seed_input):
    if seed_input is not None:
        try:
            random.seed(seed_input)
            np.random.seed(seed_input)
        except (ValueError, TypeError):
            random.seed(42)
            np.random.seed(42)
    else:
        random.seed()
        np.random.seed()

def generate_bets_by_strategy(draws, num_bets, strategy, num_count, require_pattern, trend_window, seed_input):
    """根据策略生成投注（整合所有优化方法）"""
    set_random_seed(seed_input)
    
    # 1. 计算增强版得分（整合冷热码+重复+分区）
    enhanced_scores, repeat_boost, hot_zones = calculate_enhanced_scores(draws)
    
    # 2. 获取上期数据
    last_draw = draws[-1]
    last_numbers = last_draw['numbers']
    last_special = last_draw.get('special')
    
    # 3. 根据注数动态获取和值偏移量
    sum_offset = get_sum_range_by_bets(num_bets)
    
    bets = []
    base_target = get_target_sum_by_numbers_count(num_count)
    
    if strategy == "和值大中小":
        if num_bets >= 1:
            nums, total = generate_combination(
                enhanced_scores, num_count, base_target - sum_offset, sum_offset, 
                require_pattern, last_numbers, last_special, hot_zones
            )
            bets.append({'numbers': nums, 'sum': total, 'target': f'小和值({base_target-sum_offset})', 'deviation': total - base_target})
        if num_bets >= 2:
            nums, total = generate_combination(
                enhanced_scores, num_count, base_target, sum_offset, 
                require_pattern, last_numbers, last_special, hot_zones
            )
            bets.append({'numbers': nums, 'sum': total, 'target': f'中和值({base_target})', 'deviation': total - base_target})
        if num_bets >= 3:
            nums, total = generate_combination(
                enhanced_scores, num_count, base_target + sum_offset, sum_offset, 
                require_pattern, last_numbers, last_special, hot_zones
            )
            bets.append({'numbers': nums, 'sum': total, 'target': f'大和值({base_target+sum_offset})', 'deviation': total - base_target})
        for i in range(3, num_bets):
            choice = random.choice(['小', '中', '大'])
            if choice == '小':
                target = base_target - sum_offset
            elif choice == '大':
                target = base_target + sum_offset
            else:
                target = base_target
            nums, total = generate_combination(
                enhanced_scores, num_count, target, sum_offset, 
                require_pattern, last_numbers, last_special, hot_zones
            )
            bets.append({'numbers': nums, 'sum': total, 'target': f'{choice}和值(目标{target})', 'deviation': total - base_target})
    
    elif strategy == "和值趋势预测":
        trend = predict_trend_7code(draws, window=trend_window)
        if trend == "小":
            trend_target = base_target - sum_offset
        elif trend == "大":
            trend_target = base_target + sum_offset
        else:
            trend_target = base_target
        for i in range(num_bets):
            offset = random.randint(-sum_offset, sum_offset)
            target = trend_target + offset
            target = max(25 * num_count - 2 * sum_offset, min(25 * num_count + 2 * sum_offset, target))
            nums, total = generate_combination(
                enhanced_scores, num_count, target, sum_offset, 
                require_pattern, last_numbers, last_special, hot_zones
            )
            bets.append({'numbers': nums, 'sum': total, 'target': f'{trend}和值趋势(目标{target})', 'deviation': total - base_target})
    
    else:
        half = max(1, num_bets // 2)
        if half >= 1:
            nums, total = generate_combination(
                enhanced_scores, num_count, base_target - sum_offset, sum_offset, 
                require_pattern, last_numbers, last_special, hot_zones
            )
            bets.append({'numbers': nums, 'sum': total, 'target': f'小和值({base_target-sum_offset})', 'deviation': total - base_target})
        if half >= 2:
            nums, total = generate_combination(
                enhanced_scores, num_count, base_target, sum_offset, 
                require_pattern, last_numbers, last_special, hot_zones
            )
            bets.append({'numbers': nums, 'sum': total, 'target': f'中和值({base_target})', 'deviation': total - base_target})
        if half >= 3:
            nums, total = generate_combination(
                enhanced_scores, num_count, base_target + sum_offset, sum_offset, 
                require_pattern, last_numbers, last_special, hot_zones
            )
            bets.append({'numbers': nums, 'sum': total, 'target': f'大和值({base_target+sum_offset})', 'deviation': total - base_target})
        trend = predict_trend_7code(draws, window=trend_window)
        if trend == "小":
            trend_target = base_target - sum_offset
        elif trend == "大":
            trend_target = base_target + sum_offset
        else:
            trend_target = base_target
        for i in range(num_bets - half):
            offset = random.randint(-sum_offset, sum_offset)
            target = trend_target + offset
            target = max(25 * num_count - 2 * sum_offset, min(25 * num_count + 2 * sum_offset, target))
            nums, total = generate_combination(
                enhanced_scores, num_count, target, sum_offset, 
                require_pattern, last_numbers, last_special, hot_zones
            )
            bets.append({'numbers': nums, 'sum': total, 'target': f'{trend}和值趋势(目标{target})', 'deviation': total - base_target})
    
    return bets

def calculate_match_score(bet_numbers, draw_numbers, draw_special):
    bet_main = set(bet_numbers[:6])
    draw_main = set(draw_numbers)
    main_matches = len(bet_main & draw_main)
    special_match = False
    if len(bet_numbers) >= 7:
        special_match = (bet_numbers[6] == draw_special)
    if special_match:
        return main_matches + 0.5
    else:
        return float(main_matches)

def format_score_display(score):
    if score == int(score):
        return str(int(score))
    else:
        return f"{score:.1f}"

def calculate_match_score_for_draws(bet_numbers, check_draws):
    results = []
    for draw in check_draws:
        score = calculate_match_score(bet_numbers, draw['numbers'], draw['special'])
        results.append(format_score_display(score))
    return results

def calculate_prize(match_count, special_match):
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
    set_random_seed(seed_input)
    if len(draws) < test_periods + analysis_periods:
        return None, f"数据不足：需要至少 {test_periods + analysis_periods} 期数据"
    results = []
    test_start = len(draws) - test_periods
    for i in range(test_start, len(draws)):
        train_draws = draws[:i]
        test_draw = draws[i]
        bets = generate_bets_by_strategy(
            train_draws, num_bets_per_draw, strategy,
            num_count, require_pattern, trend_window, seed_input
        )
        best_match = 0
        best_special_match = False
        best_prize = "无中奖"
        best_amount = 0
        for bet in bets:
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
    if len(match_dist) > 0:
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
    return hmac.compare_digest(password, "Ku_product$2026")

def admin_login():
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
    if st.button("退出登录", key="logout_btn"):
        st.session_state['admin_logged_in'] = False
        st.session_state['show_admin'] = False
        st.rerun()

def display_centered_dataframe(df, key=None):
    st.dataframe(df, use_container_width=True, hide_index=True, key=key)

# ==================== 管理员页面 ====================
def show_admin_page():
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
            admin_pasted = st.text_area("粘贴历史数据", height=300, key="admin_pasted", help="支持制表符、逗号或空格分隔")
            if admin_pasted:
                if st.button("预览数据", key="preview_pasted"):
                    parsed_draws = parse_pasted_data(admin_pasted)
                    if parsed_draws:
                        st.session_state['preview_draws'] = parsed_draws
                        st.success(f"成功解析 {len(parsed_draws)} 期数据")
                        display_centered_dataframe(pd.DataFrame(parsed_draws[-20:]))
                    else:
                        st.error("数据解析失败")
                if st.session_state.get('preview_draws') is not None:
                    parsed_draws = st.session_state['preview_draws']
        else:
            admin_file = st.file_uploader("上传Excel文件", type=['xlsx', 'xls'], key="admin_file")
            if admin_file:
                if st.button("预览数据", key="preview_excel"):
                    parsed_draws = parse_excel_file(admin_file)
                    if parsed_draws:
                        st.session_state['preview_draws'] = parsed_draws
                        st.success(f"成功解析 {len(parsed_draws)} 期数据")
                        display_centered_dataframe(pd.DataFrame(parsed_draws[-20:]))
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
        st.subheader("📊 策略回测")
        draws = load_draws_from_supabase()
        if draws is None or len(draws) == 0:
            st.warning("请先保存数据到Supabase，再进行回测")
        else:
            col1, col2, col3, col4, col5, col6 = st.columns(6)
            with col1:
                backtest_bets = st.number_input("回测注数", min_value=1, max_value=50, value=10, step=1, key="backtest_bets")
            with col2:
                backtest_strategy_selected = st.selectbox("回测策略", ["和值大中小", "和值趋势预测", "混合策略"], key="backtest_strategy")
            with col3:
                backtest_num_count = st.selectbox("每注号码数", [6, 7, 8, 9, 10], index=1, key="backtest_num_count")
            with col4:
                backtest_pattern = st.selectbox("连号/跳号", ["是", "否"], index=0, key="backtest_pattern")
            with col5:
                backtest_trend_window = st.number_input("趋势窗口", min_value=3, max_value=20, value=5, step=1, key="backtest_trend_window")
            with col6:
                backtest_periods = st.number_input("测试期数", min_value=5, max_value=min(100, len(draws)-50), value=min(20, len(draws)-50), step=5, key="backtest_periods")
            compare_seeds = st.button("🔬 对比多个Random Seed", type="secondary", key="compare_seeds")
            run_backtest = st.button("▶️ 运行回测", type="secondary", key="run_backtest")
            if run_backtest:
                with st.spinner("正在运行回测..."):
                    results_df, error = backtest_strategy(
                        draws, backtest_bets, backtest_strategy_selected, backtest_num_count,
                        backtest_pattern == "是", backtest_trend_window, 100, backtest_periods, 42
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
                    try:
                        results_df, error = backtest_strategy(
                            draws, backtest_bets, backtest_strategy_selected, backtest_num_count,
                            backtest_pattern == "是", backtest_trend_window, 100, backtest_periods, seed
                        )
                        if error:
                            status_text.text(f"Seed {seed}: {error}")
                        elif results_df is not None and len(results_df) > 0:
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
                    except Exception as e:
                        status_text.text(f"Seed {seed}: 错误 - {str(e)}")
                    progress_bar.progress((idx + 1) / len(seeds_to_test))
                status_text.text("对比完成！")
                if comparison_results:
                    comparison_df = pd.DataFrame(comparison_results)
                    st.dataframe(comparison_df, use_container_width=True)
                    win_rates = [float(r['中奖率'].replace('%', '')) for r in comparison_results]
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
                    st.warning("回测数据不足，请检查数据或参数设置")

# ==================== 初始化session state ====================
if 'admin_logged_in' not in st.session_state:
    st.session_state['admin_logged_in'] = False
if 'show_admin' not in st.session_state:
    st.session_state['show_admin'] = False
if 'preview_draws' not in st.session_state:
    st.session_state['preview_draws'] = None
if 'check_draws_data' not in st.session_state:
    st.session_state['check_draws_data'] = None
if 'generated_bets' not in st.session_state:
    st.session_state['generated_bets'] = None

# ==================== 右上角齿轮图标 ====================
col_title, col_settings = st.columns([0.95, 0.05])
with col_settings:
    if st.button("⚙️", key="settings_icon", help="管理员设置"):
        st.session_state['show_admin'] = not st.session_state.get('show_admin', False)

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
    with st.expander("🔥 增强版评分模型", expanded=False):
        st.latex(r"""
        \text{Score}_i = \text{BaseScore}_i + \text{RepeatBoost}_i + \text{ZoneBoost}_i
        """)
        st.markdown("""
        | 因子 | 权重 | 说明 |
        |------|------|------|
        | 冷热码评分 | 基础 | 4因子加权(0.3/0.3/0.2/0.2) |
        | 上期重复 | +2.0 | 上期号码72%概率重复 |
        | 隔期重复 | +1.0 | 上上期号码25%概率 |
        | 分区热度 | +1.2 | 热区内的号码集体加分 |
        """)
    with st.expander("📊 7分区策略", expanded=False):
        st.markdown("""
        | 分区 | 号码范围 | 特征 |
        |------|----------|------|
        | A区 | 01-07 | 极小号 |
        | B区 | 08-14 | 小号 |
        | C区 | 15-21 | 中小号 |
        | D区 | 22-28 | 中号 |
        | E区 | 29-35 | 中大号 |
        | F区 | 36-42 | 大号 |
        | G区 | 43-49 | 最大号 |
        """)
    with st.expander("📊 和值动态范围", expanded=False):
        st.markdown("""
        | 注数 | 偏移量 | 覆盖范围 |
        |------|--------|----------|
        | ≤5 | ±15 | 145-205 |
        | 6-10 | ±20 | 140-210 |
        | 11-20 | ±25 | 135-215 |
        | >20 | ±30 | 130-220 |
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
    st.caption("DFSS智能选号工具 v2.0 (增强版)")

# ==================== 主页面 ====================
st.title("🎯 六合彩AI智能选号工具")

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

# 使用增强版评分
enhanced_scores, repeat_boost, hot_zones = calculate_enhanced_scores(draws, window_total=analysis_periods)

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("**🔥 热门号码 (Top 15)**")
    hot_df = pd.DataFrame([
        {'号码': num, '得分': f"{enhanced_scores[num]:.2f}", '重复加分': f"{repeat_boost[num]:.1f}"}
        for num in sorted(enhanced_scores, key=enhanced_scores.get, reverse=True)[:15]
    ])
    display_centered_dataframe(hot_df)
with col2:
    st.markdown("**❄️ 冷门号码 (Bottom 10)**")
    cold_df = pd.DataFrame([
        {'号码': num, '得分': f"{enhanced_scores[num]:.2f}", '重复加分': f"{repeat_boost[num]:.1f}"}
        for num in sorted(enhanced_scores, key=enhanced_scores.get)[:10]
    ])
    display_centered_dataframe(cold_df)
with col3:
    st.markdown("**🔥 当前热区 (7分区)**")
    st.markdown(f"""
    | 分区 | 号码范围 | 热度 |
    |------|----------|------|
    | A区 | 01-07 | {'🔥' if 1 in hot_zones else '❄️'} |
    | B区 | 08-14 | {'🔥' if 2 in hot_zones else '❄️'} |
    | C区 | 15-21 | {'🔥' if 3 in hot_zones else '❄️'} |
    | D区 | 22-28 | {'🔥' if 4 in hot_zones else '❄️'} |
    | E区 | 29-35 | {'🔥' if 5 in hot_zones else '❄️'} |
    | F区 | 36-42 | {'🔥' if 6 in hot_zones else '❄️'} |
    | G区 | 43-49 | {'🔥' if 7 in hot_zones else '❄️'} |
    """)
    st.caption(f"当前热区: {', '.join([f'{z}区' for z in hot_zones])}")

# ==================== 和值趋势分析（以7码显示） ====================
st.subheader("📈 和值趋势分析（7个号码）")
show_periods = st.slider(
    "显示最近期数",
    min_value=10,
    max_value=min(200, len(draws)),
    value=min(100, len(draws)),
    step=10
)
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
next_period = latest_period + 1 if isinstance(latest_period, int) else "N/A"
st.info(f"🎯 **预测下一期**: {next_period}")

col1, col2, col3, col4 = st.columns(4)
with col1:
    num_bets = st.number_input(
        "购买注数",
        min_value=1,
        max_value=50,
        value=10,
        step=1,
        help="每次购买多少注（最多50注）"
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

# 显示动态和值范围提示
sum_offset = get_sum_range_by_bets(num_bets)
st.caption(f"💡 提示：当前 {num_bets} 注，和值范围已自动放宽至 **±{sum_offset}**（覆盖 {175-sum_offset}~{175+sum_offset}），注数越多范围越大。")

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
    bets = generate_bets_by_strategy(
        draws, num_bets, strategy,
        num_count, require_pattern == "是", trend_window, random_seed
    )
    st.session_state['generated_bets'] = bets
    st.session_state['bets_display_seed'] = seed_display
    st.session_state['bets_require_pattern'] = require_pattern
    st.session_state['bets_trend_window'] = trend_window
    st.session_state['bets_use_analysis_periods'] = use_analysis_periods
    st.session_state['bets_strategy'] = strategy
    st.session_state['bets_num_count'] = num_count

if st.session_state['generated_bets'] is not None:
    bets = st.session_state['generated_bets']
    st.markdown("### 📝 推荐投注组合")
    st.markdown(f"""
    **⚙️ 当前设置**
    - Random Seed: `{st.session_state['bets_display_seed']}`
    - 连号/跳号要求: {st.session_state['bets_require_pattern']}
    - 趋势窗口: {st.session_state['bets_trend_window']}期
    - 和值范围: ±{get_sum_range_by_bets(len(bets))}
    """)
    
    bets_data = []
    for i, bet in enumerate(bets, 1):
        numbers_display = ','.join(str(n) for n in bet['numbers'])
        row = {
            '注数': i,
            '推荐号码': numbers_display,
            '和值': bet['sum'],
            '目标策略': bet['target'],
            '偏差': f"{bet['deviation']:+d}" if bet['deviation'] != 0 else "0"
        }
        bets_data.append(row)
    
    base_bets_df = pd.DataFrame(bets_data)
    display_centered_dataframe(base_bets_df)
    
    st.info(f"""
    📊 **预测信息**
    - 使用最近 {st.session_state['bets_use_analysis_periods']} 期数据进行分析
    - 当前策略: {st.session_state['bets_strategy']}
    - 共生成 {len(bets)} 注推荐号码
    - 每注 {st.session_state['bets_num_count']} 个号码
    - 理论期望和值: {get_target_sum_by_numbers_count(st.session_state['bets_num_count'])}
    """)
    
    if st.session_state['bets_num_count'] == 7:
        st.caption("💡 提示: 7个号码包含6个正码和1个特码，格式如: 1,2,3,4,5,6,7")
    
    # ==================== 多期查奖窗口（放在表格后面） ====================
    st.markdown("---")
    st.markdown("### 🔍 多期查奖")
    check_col1, check_col2 = st.columns([2, 1])
    with check_col1:
        check_draws_text = st.text_area(
            "📋 粘贴多期开奖数据（最多5期）",
            height=150,
            key="check_draws_text_area",
            placeholder="""示例格式：
26045\t2026-04-25\t4\t16\t21\t36\t42\t46\t9
26046\t2026-04-28\t5\t12\t18\t29\t35\t44\t7
26047\t2026-05-02\t8\t14\t22\t31\t39\t47\t12

支持制表符、逗号或空格分隔，最后一列为特码
最多支持5期
            """
        )
        check_btn = st.button("🔍 查奖", key="check_prize_btn")
    with check_col2:
        st.markdown("""
        **📌 说明**
        - 最后一列 = 特码
        - 前6列 = 正码
        - 最多粘贴 **5期**
        
        **中奖个数计算**
        - 正码匹配 = 1分
        - 特码匹配 = 0.5分
        - 显示格式: `3` 或 `3.5`
        """)
    
    if check_btn and check_draws_text:
        check_draws = parse_multi_draws_for_checking(check_draws_text, max_draws=5)
        if check_draws:
            st.success(f"✅ 成功解析 {len(check_draws)} 期数据")
            enhanced_bets_data = []
            for i, bet in enumerate(bets, 1):
                numbers_display = ','.join(str(n) for n in bet['numbers'])
                row = {
                    '注数': i,
                    '推荐号码': numbers_display,
                    '和值': bet['sum'],
                    '目标策略': bet['target'],
                    '偏差': f"{bet['deviation']:+d}" if bet['deviation'] != 0 else "0"
                }
                match_scores = calculate_match_score_for_draws(bet['numbers'], check_draws)
                for idx, draw in enumerate(check_draws):
                    period_str = str(draw['period'])
                    if len(period_str) > 10:
                        period_str = period_str[-10:]
                    row[f'中奖_{period_str}'] = match_scores[idx]
                enhanced_bets_data.append(row)
            enhanced_df = pd.DataFrame(enhanced_bets_data)
            rename_dict = {}
            for col in enhanced_df.columns:
                if col.startswith('中奖_'):
                    rename_dict[col] = col.replace('中奖_', '')
            enhanced_df = enhanced_df.rename(columns=rename_dict)
            display_centered_dataframe(enhanced_df)
            if len(check_draws) > 3:
                with st.container(height=200):
                    preview_df = pd.DataFrame([
                        {'期次': d['period'], '正码': str(d['numbers']), '特码': d['special']}
                        for d in check_draws
                    ])
                    display_centered_dataframe(preview_df)
            else:
                preview_df = pd.DataFrame([
                    {'期次': d['period'], '正码': str(d['numbers']), '特码': d['special']}
                    for d in check_draws
                ])
                display_centered_dataframe(preview_df)
        else:
            st.error("❌ 解析失败，请检查格式")

st.markdown("---")
st.caption("⚠️ 本工具仅供学术研究和娱乐参考。六合彩本质上是一种随机游戏，长期期望值为负，请理性投注。")
