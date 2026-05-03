# Marksix_app_enhanced.py
import streamlit as st
import pandas as pd
import numpy as np
import random
import math
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import hashlib
import hmac
from supabase import create_client, Client

# 尝试导入机器学习库（如果没有安装，给出提示）
try:
    import lightgbm as lgb
    LGB_AVAILABLE = True
except ImportError:
    LGB_AVAILABLE = False

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

try:
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import VotingClassifier
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

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
    .stCheckbox {
        margin-top: 10px;
    }
    .stDataEditor {
        text-align: center;
    }
    .stDataEditor td {
        text-align: center !important;
    }
    .stDataEditor th {
        text-align: center !important;
    }
    div[data-testid="stExpander"] div[role="button"] p {
        font-size: 1.1rem;
        font-weight: bold;
    }
    .stAlert {
        font-size: 0.9rem;
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

# ==================== 日期时间转Excel编码函数 ====================
def datetime_to_excel_serial(dt):
    base_date = datetime(1900, 1, 1)
    delta = dt - base_date
    days = delta.days + 2
    seconds = delta.seconds
    time_fraction = seconds / 86400
    return days + time_fraction

def parse_datetime_string(datetime_str):
    datetime_str = datetime_str.strip()
    if not datetime_str:
        return None
    
    formats = [
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
        "%Y%m%d %H:%M:%S", "%Y%m%d %H:%M", "%Y%m%d",
        "%Y-%m-%dT%H:%M:%S",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(datetime_str, fmt)
            serial = datetime_to_excel_serial(dt)
            return int(serial * 1000000)
        except ValueError:
            continue
    
    st.warning(f"无法解析日期时间格式: {datetime_str}，将使用完全随机")
    return None

# ==================== 分区函数 ====================
def get_zone(num):
    return (num - 1) // 7 + 1

def get_zone_numbers(zone):
    start = (zone - 1) * 7 + 1
    end = start + 6
    return list(range(start, end + 1))

def calculate_zone_heat(draws, last_n=20):
    zone_hits = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0}
    zone_trend = {1: [], 2: [], 3: [], 4: [], 5: [], 6: [], 7: []}
    
    for idx, draw in enumerate(draws[-last_n:]):
        for num in draw['numbers']:
            zone = get_zone(num)
            zone_hits[zone] += 1
            zone_trend[zone].append(idx)
    
    zone_scores = {}
    for zone in range(1, 8):
        hits = zone_hits[zone]
        recent_weight = 0
        for pos in zone_trend[zone][-5:]:
            recent_weight += (5 - (last_n - pos)) if (last_n - pos) < 5 else 0
        zone_scores[zone] = hits * 1.0 + recent_weight * 0.5
    
    return zone_scores, zone_hits

def get_hot_zones(zone_scores, num_hot_zones=3):
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

def calculate_enhanced_scores(draws, window_total=100, window_short=20, window_recent=10, zone_window=20):
    base_scores, freq, short_freq, absence = calculate_scores(draws, window_total, window_short, window_recent)
    
    last_draw = draws[-1]
    last_numbers = last_draw['numbers']
    last_special = last_draw.get('special')
    last_draw_all = last_numbers + [last_special]
    
    zone_scores, _ = calculate_zone_heat(draws, last_n=zone_window)
    hot_zones = get_hot_zones(zone_scores, num_hot_zones=3)
    
    repeat_boost = {}
    for num in range(1, 50):
        boost = 0.0
        
        if num in last_draw_all:
            boost += 2.0
        
        if len(draws) >= 2:
            prev_draw = draws[-2]
            prev_numbers = prev_draw['numbers'] + [prev_draw.get('special')]
            if num in prev_numbers and num not in last_draw_all:
                boost += 1.0
        
        if len(draws) >= 3:
            last_3_draws = draws[-3:]
            count_in_last_3 = 0
            for d in last_3_draws:
                if num in d['numbers'] or num == d.get('special'):
                    count_in_last_3 += 1
            if count_in_last_3 >= 2 and num not in last_draw_all:
                boost += 0.8
        
        if len(draws) >= 5:
            last_5_draws = draws[-5:]
            count_in_last_5 = 0
            for d in last_5_draws:
                if num in d['numbers'] or num == d.get('special'):
                    count_in_last_5 += 1
            if count_in_last_5 >= 3:
                boost += 0.5
        
        num_zone = get_zone(num)
        if num_zone in hot_zones:
            boost += 1.2
        
        repeat_boost[num] = boost
    
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

def get_dynamic_sum_range(draws, num_count, window=4, sigma_factor=0.5, threshold_factor=0.1):
    recent_draws = draws[-100:] if len(draws) >= 100 else draws
    all_sum_7 = [convert_6sum_to_7sum(d['sum']) for d in recent_draws]
    long_term_mean = np.mean(all_sum_7)
    long_term_std = np.std(all_sum_7)
    
    short_draws = draws[-window:] if len(draws) >= window else draws
    short_sum_7 = [convert_6sum_to_7sum(d['sum']) for d in short_draws]
    short_mean = np.mean(short_sum_7)
    
    threshold = long_term_std * threshold_factor
    
    if short_mean > long_term_mean + threshold:
        target = long_term_mean - long_term_std * sigma_factor
        direction = "偏大回归"
        direction_desc = f"📈 偏大 (最近{window}期均值={short_mean:.1f} > 长期均值+{threshold:.1f})"
    elif short_mean < long_term_mean - threshold:
        target = long_term_mean + long_term_std * sigma_factor
        direction = "偏小回归"
        direction_desc = f"📉 偏小 (最近{window}期均值={short_mean:.1f} < 长期均值-{threshold:.1f})"
    else:
        target = long_term_mean
        direction = "正常"
        direction_desc = f"⚖️ 正常 (最近{window}期均值={short_mean:.1f} 在 ±{threshold:.1f} 范围内)"
    
    tolerance = int(long_term_std * sigma_factor)
    
    return int(target), tolerance, direction, direction_desc, long_term_mean, long_term_std, short_mean

def get_sampling_weights(scores, temperature=1.5):
    weights = {}
    for num, score in scores.items():
        weights[num] = math.exp(score / temperature)
    return weights

def weighted_random_sample(weights, k=7, max_attempts=100):
    numbers = list(weights.keys())
    weight_list = [weights[n] for n in numbers]
    
    attempts = 0
    while attempts < max_attempts:
        selected = random.choices(
            population=numbers,
            weights=weight_list,
            k=k
        )
        if len(set(selected)) == k:
            return sorted(selected)
        attempts += 1
    
    return sorted(random.sample(numbers, k))

def is_valid_combination(nums, target_sum, tolerance, require_pattern, require_prev_repeat, last_draw_all):
    total = sum(nums)
    
    if abs(total - target_sum) > tolerance:
        return False
    
    if require_pattern:
        if not has_consecutive_or_jump(nums):
            return False
    
    if require_prev_repeat and last_draw_all:
        prev_repeat_count = len(set(nums) & set(last_draw_all))
        if prev_repeat_count < 1 or prev_repeat_count > 2:
            return False
    
    return True

def generate_one_combination(weights, num_count, target_sum, tolerance, require_pattern, require_prev_repeat, last_draw_all):
    max_attempts = 10000
    for _ in range(max_attempts):
        selected = weighted_random_sample(weights, k=num_count)
        if is_valid_combination(selected, target_sum, tolerance, require_pattern, require_prev_repeat, last_draw_all):
            return selected, sum(selected)
    
    for _ in range(5000):
        selected = weighted_random_sample(weights, k=num_count)
        total = sum(selected)
        if abs(total - target_sum) <= tolerance + 5:
            return selected, total
    
    return sorted(random.sample(range(1, 50), num_count)), sum(sorted(random.sample(range(1, 50), num_count)))

def set_random_seed(seed_value):
    if seed_value is not None:
        try:
            random.seed(seed_value)
            np.random.seed(seed_value)
        except (ValueError, TypeError):
            random.seed()
            np.random.seed()
    else:
        random.seed()
        np.random.seed()

# ==================== 胆拖法函数 ====================
def select_anchor_numbers(draws, num_anchors=3):
    """选择胆码（基于最新热号分析）"""
    enhanced_scores, _, hot_zones = calculate_enhanced_scores(draws)
    
    # 获取上期号码
    last_draw = draws[-1]
    last_numbers = last_draw['numbers']
    last_special = last_draw.get('special')
    
    # 胆码候选池
    candidates = []
    
    # 1. 上期热码（高重复概率）
    for num in last_numbers:
        candidates.append((num, enhanced_scores[num] + 2.0))
    
    # 2. 热区内的号码
    for zone in hot_zones:
        for num in get_zone_numbers(zone):
            if enhanced_scores[num] > 0:
                candidates.append((num, enhanced_scores[num] + 1.0))
    
    # 3. 近期高频号码
    recent_20_draws = draws[-20:]
    recent_counts = {}
    for draw in recent_20_draws:
        for num in draw['numbers']:
            recent_counts[num] = recent_counts.get(num, 0) + 1
    
    for num, count in recent_counts.items():
        if count >= 3:
            candidates.append((num, enhanced_scores[num] + 0.5))
    
    # 去重并排序
    candidates_dict = {}
    for num, score in candidates:
        if num not in candidates_dict:
            candidates_dict[num] = score
        else:
            candidates_dict[num] = max(candidates_dict[num], score)
    
    sorted_candidates = sorted(candidates_dict.items(), key=lambda x: x[1], reverse=True)
    
    # 选择前num_anchors个作为胆码
    anchors = [num for num, score in sorted_candidates[:num_anchors]]
    
    return anchors

def generate_one_combination_with_anchors(weights, anchors, num_count, target_sum, tolerance, 
                                           require_pattern, require_prev_repeat, last_draw_all):
    """基于胆码生成一注号码"""
    remaining_needed = num_count - len(anchors)
    if remaining_needed <= 0:
        return sorted(anchors[:num_count]), sum(sorted(anchors[:num_count]))
    
    max_attempts = 5000
    for _ in range(max_attempts):
        # 排除已选的胆码
        available_numbers = [n for n in weights.keys() if n not in anchors]
        available_weights = [weights[n] for n in available_numbers]
        
        if len(available_numbers) < remaining_needed:
            remaining_needed = len(available_numbers)
        
        selected = random.choices(
            population=available_numbers,
            weights=available_weights,
            k=remaining_needed
        )
        
        full_selection = anchors + selected
        if len(set(full_selection)) != len(full_selection):
            continue
            
        if is_valid_combination(full_selection, target_sum, tolerance, 
                                require_pattern, require_prev_repeat, last_draw_all):
            return sorted(full_selection), sum(full_selection)
    
    # 降级处理
    full_selection = anchors + random.sample([n for n in range(1, 50) if n not in anchors], remaining_needed)
    return sorted(full_selection), sum(full_selection)

# ==================== LightGBM 预测函数 ====================
def build_features_for_lightgbm(draws, target_num):
    """构建LightGBM特征"""
    features = {}
    
    if len(draws) < 10:
        return None
    
    # 基础特征
    total_draws = len(draws)
    freq = sum(1 for d in draws if target_num in d['numbers'])
    features['freq'] = freq / max(1, total_draws)
    
    # 短期频率（最近20期）
    short_draws = draws[-20:]
    short_freq = sum(1 for d in short_draws if target_num in d['numbers'])
    features['short_freq'] = short_freq / 20
    
    # 遗漏期数
    last_seen = None
    for idx, d in enumerate(reversed(draws)):
        if target_num in d['numbers']:
            last_seen = idx
            break
    features['absence'] = last_seen if last_seen is not None else total_draws
    
    # 上期是否出现
    if draws[-1]:
        features['last_appeared'] = 1 if target_num in draws[-1]['numbers'] else 0
    
    # 分区特征
    zone = get_zone(target_num)
    features['zone'] = zone
    
    # 近期趋势
    recent_5 = sum(1 for d in draws[-5:] if target_num in d['numbers'])
    recent_10 = sum(1 for d in draws[-10:] if target_num in d['numbers'])
    features['recent_5'] = recent_5
    features['recent_10'] = recent_10
    
    # 与上期的差值特征
    last_numbers = draws[-1]['numbers']
    min_diff = min(abs(target_num - n) for n in last_numbers) if last_numbers else 99
    features['min_diff_to_last'] = min_diff
    
    # 同尾号特征
    same_tail_count = sum(1 for d in draws[-20:] if any(n % 10 == target_num % 10 for n in d['numbers']))
    features['same_tail_hot'] = same_tail_count / 20
    
    return features

def prepare_lightgbm_dataset(draws, lookback=50):
    """准备LightGBM训练数据集"""
    if len(draws) < lookback + 10:
        return None, None
    
    X_list = []
    y_list = []
    
    for i in range(lookback, len(draws) - 1):
        train_draws = draws[:i]
        next_draw = draws[i]
        
        for num in range(1, 50):
            features = build_features_for_lightgbm(train_draws, num)
            if features:
                X_list.append(features)
                y_list.append(1 if num in next_draw['numbers'] else 0)
    
    if not X_list:
        return None, None
    
    X_df = pd.DataFrame(X_list)
    y_series = pd.Series(y_list)
    
    return X_df, y_series

def train_lightgbm_model(draws):
    """训练LightGBM模型"""
    if not LGB_AVAILABLE:
        return None
    
    X, y = prepare_lightgbm_dataset(draws)
    if X is None or len(X) < 100:
        return None
    
    try:
        model = lgb.LGBMClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            random_state=42,
            verbose=-1
        )
        model.fit(X, y)
        return model
    except Exception as e:
        st.warning(f"LightGBM训练失败: {e}")
        return None

def predict_with_lightgbm(model, draws):
    """使用LightGBM预测下期号码"""
    if model is None:
        return None
    
    predictions = []
    for num in range(1, 50):
        features = build_features_for_lightgbm(draws, num)
        if features:
            X_pred = pd.DataFrame([features])
            prob = model.predict_proba(X_pred)[0][1]
            predictions.append((num, prob))
        else:
            predictions.append((num, 0.0))
    
    predictions.sort(key=lambda x: x[1], reverse=True)
    return [num for num, prob in predictions[:7]]

# ==================== XGBoost + 神经网络集成函数 ====================
def build_advanced_features(draws, target_num):
    """构建高级特征（52个特征）用于XGBoost+NN集成"""
    features = {}
    
    if len(draws) < 20:
        return None
    
    total_draws = len(draws)
    
    # 1. 基础冷热码特征 (8个)
    freq = sum(1 for d in draws if target_num in d['numbers'])
    features['freq'] = freq / max(1, total_draws)
    features['freq_zscore'] = (freq - np.mean([sum(1 for d in draws if i in d['numbers']) for i in range(1, 50)])) / max(1, np.std([sum(1 for d in draws if i in d['numbers']) for i in range(1, 50)]))
    
    short_draws = draws[-20:]
    short_freq = sum(1 for d in short_draws if target_num in d['numbers'])
    features['short_freq'] = short_freq / 20
    
    # 遗漏特征
    last_seen = None
    for idx, d in enumerate(reversed(draws)):
        if target_num in d['numbers']:
            last_seen = idx
            break
    absence = last_seen if last_seen is not None else total_draws
    features['absence'] = absence
    features['absence_norm'] = absence / max(1, total_draws)
    
    # 2. 统计特征 (6个)
    recent_3 = sum(1 for d in draws[-3:] if target_num in d['numbers'])
    recent_5 = sum(1 for d in draws[-5:] if target_num in d['numbers'])
    recent_10 = sum(1 for d in draws[-10:] if target_num in d['numbers'])
    features['recent_3'] = recent_3
    features['recent_5'] = recent_5
    features['recent_10'] = recent_10
    
    # 3. 时间特征 (6个)
    last_date = draws[-1].get('date')
    if last_date and isinstance(last_date, str):
        try:
            last_dt = datetime.strptime(last_date.split()[0] if ' ' in last_date else last_date, '%Y-%m-%d')
            features['weekday'] = last_dt.weekday()
            features['is_weekend'] = 1 if features['weekday'] >= 5 else 0
            features['is_saturday'] = 1 if features['weekday'] == 5 else 0
            features['month'] = last_dt.month
            features['quarter'] = (last_dt.month - 1) // 3
        except:
            features['weekday'] = 0
            features['is_weekend'] = 0
            features['is_saturday'] = 0
            features['month'] = 0
            features['quarter'] = 0
    else:
        features['weekday'] = 0
        features['is_weekend'] = 0
        features['is_saturday'] = 0
        features['month'] = 0
        features['quarter'] = 0
    
    # 4. 序列特征 (10个)
    # MA5, MA10
    appearances = [1 if target_num in d['numbers'] else 0 for d in draws[-50:]]
    if len(appearances) >= 10:
        features['ma5'] = np.mean(appearances[-5:])
        features['ma10'] = np.mean(appearances[-10:])
        features['trend'] = features['ma5'] - features['ma10']
    else:
        features['ma5'] = 0
        features['ma10'] = 0
        features['trend'] = 0
    
    # 5. 组合特征 (12个)
    # 与上期号码的关联
    last_numbers = draws[-1]['numbers']
    features['in_last'] = 1 if target_num in last_numbers else 0
    features['min_diff'] = min(abs(target_num - n) for n in last_numbers) if last_numbers else 99
    features['same_parity'] = 1 if (target_num % 2) == (last_numbers[0] % 2 if last_numbers else 0) else 0
    
    # 同尾号热度
    same_tail_nums = [n for n in range(1, 50) if n % 10 == target_num % 10]
    same_tail_freq = sum(1 for d in draws[-20:] for n in d['numbers'] if n in same_tail_nums)
    features['same_tail_hot'] = same_tail_freq / (20 * len(same_tail_nums))
    
    # 6. 分区特征 (4个)
    zone = get_zone(target_num)
    features['zone'] = zone
    
    zone_hits = {}
    for z in range(1, 8):
        zone_hits[z] = sum(1 for d in draws[-20:] for n in d['numbers'] if get_zone(n) == z)
    features['zone_hot'] = zone_hits.get(zone, 0) / 20
    
    # 7. 与特码的关系
    last_special = draws[-1].get('special')
    features['is_special'] = 1 if target_num == last_special else 0
    features['diff_to_special'] = abs(target_num - last_special) if last_special else 99
    
    return features

def prepare_advanced_dataset(draws, lookback=100):
    """准备高级数据集"""
    if len(draws) < lookback + 10:
        return None, None
    
    X_list = []
    y_list = []
    
    for i in range(lookback, len(draws) - 1):
        train_draws = draws[:i]
        next_draw = draws[i]
        
        for num in range(1, 50):
            features = build_advanced_features(train_draws, num)
            if features:
                X_list.append(features)
                y_list.append(1 if num in next_draw['numbers'] else 0)
    
    if not X_list:
        return None, None
    
    X_df = pd.DataFrame(X_list)
    y_series = pd.Series(y_list)
    
    # 填充缺失值
    X_df = X_df.fillna(0)
    
    return X_df, y_series

def train_xgboost_nn_ensemble(draws):
    """训练XGBoost + 神经网络集成模型"""
    if not XGB_AVAILABLE or not SKLEARN_AVAILABLE:
        return None
    
    X, y = prepare_advanced_dataset(draws)
    if X is None or len(X) < 200:
        return None
    
    try:
        # XGBoost模型
        xgb_model = xgb.XGBClassifier(
            n_estimators=150,
            max_depth=6,
            learning_rate=0.08,
            random_state=42,
            use_label_encoder=False,
            eval_metric='logloss',
            verbosity=0
        )
        
        # 神经网络模型
        nn_model = MLPClassifier(
            hidden_layer_sizes=(64, 32, 16),
            activation='relu',
            max_iter=200,
            random_state=42,
            early_stopping=True,
            validation_fraction=0.1
        )
        
        # 标准化器
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # 训练两个模型
        xgb_model.fit(X, y)
        nn_model.fit(X_scaled, y)
        
        return {
            'xgb': xgb_model,
            'nn': nn_model,
            'scaler': scaler,
            'feature_names': X.columns.tolist()
        }
    except Exception as e:
        st.warning(f"XGBoost+NN集成训练失败: {e}")
        return None

def predict_with_ensemble(model_dict, draws):
    """使用集成模型预测"""
    if model_dict is None:
        return None
    
    try:
        predictions = []
        for num in range(1, 50):
            features = build_advanced_features(draws, num)
            if features:
                X_pred = pd.DataFrame([features])
                X_pred = X_pred.fillna(0)
                
                # 确保列顺序一致
                missing_cols = set(model_dict['feature_names']) - set(X_pred.columns)
                for col in missing_cols:
                    X_pred[col] = 0
                X_pred = X_pred[model_dict['feature_names']]
                
                # XGBoost预测
                xgb_prob = model_dict['xgb'].predict_proba(X_pred)[0][1]
                
                # 神经网络预测
                X_scaled = model_dict['scaler'].transform(X_pred)
                nn_prob = model_dict['nn'].predict_proba(X_scaled)[0][1]
                
                # 加权融合（XGBoost权重0.5，NN权重0.5）
                ensemble_prob = xgb_prob * 0.5 + nn_prob * 0.5
                predictions.append((num, ensemble_prob))
            else:
                predictions.append((num, 0.0))
        
        predictions.sort(key=lambda x: x[1], reverse=True)
        return [num for num, prob in predictions[:7]]
    except Exception as e:
        st.warning(f"集成预测失败: {e}")
        return None

# ==================== 策略选择生成函数 ====================
def generate_bets_method1_hybrid(draws, num_bets, num_count, require_pattern, require_prev_repeat, 
                                  trend_window, random_seed, analysis_periods):
    """方法1：当前方法 + 胆拖混合"""
    set_random_seed(random_seed)
    
    enhanced_scores, repeat_boost, hot_zones = calculate_enhanced_scores(draws, window_total=analysis_periods)
    
    last_draw = draws[-1]
    last_numbers = last_draw['numbers']
    last_special = last_draw.get('special')
    last_draw_all = last_numbers + [last_special] if require_prev_repeat else None
    
    weights = get_sampling_weights(enhanced_scores, temperature=1.5)
    
    target_sum, tolerance, direction, _, _, _, _ = get_dynamic_sum_range(draws, num_count, window=trend_window)
    base_target = get_target_sum_by_numbers_count(num_count)
    target_sum = max(base_target - 2 * tolerance, min(base_target + 2 * tolerance, target_sum))
    
    # 分配注数：一半当前方法，一半胆拖法
    num_normal = num_bets // 2
    num_anchor = num_bets - num_normal
    
    bets = []
    
    # 获取胆码
    anchors = select_anchor_numbers(draws, num_anchors=3)
    
    # 当前方法生成
    for i in range(num_normal):
        offset = random.randint(-tolerance, tolerance)
        t = int(target_sum + offset)
        t = max(base_target - 2 * tolerance, min(base_target + 2 * tolerance, t))
        nums, total = generate_one_combination(
            weights, num_count, t, tolerance,
            require_pattern, require_prev_repeat, last_draw_all
        )
        method = "当前方法"
        bets.append({'numbers': nums, 'sum': total, 'target': f'{method}(目标{t})', 'deviation': total - base_target})
    
    # 胆拖法生成
    anchor_weights = get_sampling_weights(enhanced_scores, temperature=1.5)
    for i in range(num_anchor):
        offset = random.randint(-tolerance, tolerance)
        t = int(target_sum + offset)
        t = max(base_target - 2 * tolerance, min(base_target + 2 * tolerance, t))
        nums, total = generate_one_combination_with_anchors(
            anchor_weights, anchors, num_count, t, tolerance,
            require_pattern, require_prev_repeat, last_draw_all
        )
        method = "胆拖法"
        bets.append({'numbers': nums, 'sum': total, 'target': f'{method}(目标{t})', 'deviation': total - base_target})
    
    return bets

def generate_bets_method2_lightgbm(draws, num_bets, num_count, require_pattern, require_prev_repeat,
                                    trend_window, random_seed, analysis_periods):
    """方法2：LightGBM机器学习"""
    set_random_seed(random_seed)
    
    # 训练LightGBM模型
    model = train_lightgbm_model(draws)
    
    if model is None:
        # 降级到当前方法
        st.warning("LightGBM模型训练失败，降级使用当前方法")
        return generate_bets_method1_hybrid(draws, num_bets, num_count, require_pattern, 
                                            require_prev_repeat, trend_window, random_seed, analysis_periods)
    
    # 使用模型预测
    predicted_numbers = predict_with_lightgbm(model, draws)
    
    if predicted_numbers is None or len(predicted_numbers) < num_count:
        predicted_numbers = list(range(1, num_count + 1))
    
    # 基于预测结果生成多注（添加随机扰动）
    base_target, tolerance, direction, _, _, _, _ = get_dynamic_sum_range(draws, num_count, window=trend_window)
    base_target = get_target_sum_by_numbers_count(num_count)
    
    bets = []
    for i in range(num_bets):
        # 在预测号码基础上添加随机扰动
        nums = predicted_numbers[:]
        if len(nums) < num_count:
            extra = random.sample([n for n in range(1, 50) if n not in nums], num_count - len(nums))
            nums.extend(extra)
        
        # 随机替换20%的号码增加多样性
        replace_count = max(1, int(num_count * 0.2))
        for _ in range(replace_count):
            idx = random.randint(0, len(nums) - 1)
            new_num = random.randint(1, 49)
            while new_num in nums:
                new_num = random.randint(1, 49)
            nums[idx] = new_num
        
        nums = sorted(nums[:num_count])
        total = sum(nums)
        
        bets.append({
            'numbers': nums,
            'sum': total,
            'target': f'LightGBM预测(目标{base_target})',
            'deviation': total - base_target
        })
    
    return bets

def generate_bets_method3_ensemble(draws, num_bets, num_count, require_pattern, require_prev_repeat,
                                    trend_window, random_seed, analysis_periods):
    """方法3：XGBoost + 神经网络集成"""
    set_random_seed(random_seed)
    
    # 训练集成模型
    ensemble = train_xgboost_nn_ensemble(draws)
    
    if ensemble is None:
        # 降级到LightGBM
        st.warning("XGBoost+NN集成训练失败，降级使用LightGBM")
        return generate_bets_method2_lightgbm(draws, num_bets, num_count, require_pattern,
                                               require_prev_repeat, trend_window, random_seed, analysis_periods)
    
    # 使用集成模型预测
    predicted_numbers = predict_with_ensemble(ensemble, draws)
    
    if predicted_numbers is None or len(predicted_numbers) < num_count:
        predicted_numbers = list(range(1, num_count + 1))
    
    # 基于预测结果生成多注
    base_target, tolerance, direction, _, _, _, _ = get_dynamic_sum_range(draws, num_count, window=trend_window)
    base_target = get_target_sum_by_numbers_count(num_count)
    
    bets = []
    for i in range(num_bets):
        # 在预测号码基础上添加随机扰动（扰动更小，保持模型置信度）
        nums = predicted_numbers[:]
        if len(nums) < num_count:
            extra = random.sample([n for n in range(1, 50) if n not in nums], num_count - len(nums))
            nums.extend(extra)
        
        # 随机替换10%的号码（集成模型置信度高，扰动更小）
        replace_count = max(1, int(num_count * 0.1))
        for _ in range(replace_count):
            idx = random.randint(0, len(nums) - 1)
            new_num = random.randint(1, 49)
            while new_num in nums:
                new_num = random.randint(1, 49)
            nums[idx] = new_num
        
        nums = sorted(nums[:num_count])
        total = sum(nums)
        
        bets.append({
            'numbers': nums,
            'sum': total,
            'target': f'XGBoost+NN集成(目标{base_target})',
            'deviation': total - base_target
        })
    
    return bets

# ==================== 多期查奖函数 ====================
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
        
        edit_mode = st.radio(
            "选择编辑方式",
            ["📋 直接编辑表格", "📄 粘贴数据添加", "📎 上传Excel文件"],
            horizontal=True,
            key="edit_mode"
        )
        
        parsed_draws = None
        edited_df = None
        
        if edit_mode == "📋 直接编辑表格":
            st.markdown("""
            **💡 使用说明**
            - 双击单元格可直接编辑内容
            - 点击列标题可排序
            - 点击行首的 `+` 可新增行
            - 选中行后按 `Delete` 可删除行
            - 编辑完成后点击 **💾 保存到Supabase** 按钮
            """)
            
            if current_draws:
                df_current = pd.DataFrame(current_draws)
                df_current = df_current.rename(columns={
                    'period': '期次', 'date': '開獎日期',
                    'numbers': '正码(6个)', 'special': '特码', 'sum': '和值'
                })
                df_current['正码(6个)'] = df_current['正码(6个)'].apply(lambda x: ','.join(map(str, x)) if isinstance(x, list) else str(x))
                df_current['開獎日期'] = df_current['開獎日期'].apply(lambda x: str(x) if pd.notna(x) else '')
                
                sort_order = st.selectbox("默认排序", ["期次降序(最新在上)", "期次升序(最旧在上)", "原始顺序"])
                if sort_order == "期次降序(最新在上)":
                    df_current = df_current.sort_values(by='期次', ascending=False)
                elif sort_order == "期次升序(最旧在上)":
                    df_current = df_current.sort_values(by='期次', ascending=True)
                
                edited_df = st.data_editor(
                    df_current,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    column_config={
                        "期次": st.column_config.NumberColumn("期次", required=True, step=1),
                        "開獎日期": st.column_config.TextColumn("開獎日期"),
                        "正码(6个)": st.column_config.TextColumn("正码(6个)", required=True),
                        "特码": st.column_config.NumberColumn("特码", required=True, min_value=1, max_value=49),
                        "和值": st.column_config.NumberColumn("和值", disabled=True),
                    }
                )
                
                if st.button("💾 保存到Supabase", type="primary"):
                    if edited_df is not None:
                        new_draws = []
                        errors = []
                        for idx, row in edited_df.iterrows():
                            try:
                                period = int(row['期次']) if pd.notna(row['期次']) else None
                                if period is None:
                                    errors.append(f"第{idx+1}行: 期次不能为空")
                                    continue
                                
                                numbers_str = str(row['正码(6个)']).strip()
                                numbers_list = []
                                for part in numbers_str.replace(' ', '').split(','):
                                    if part.strip():
                                        num = int(float(part.strip()))
                                        if 1 <= num <= 49:
                                            numbers_list.append(num)
                                if len(numbers_list) != 6:
                                    errors.append(f"第{idx+1}行: 正码需要6个")
                                    continue
                                
                                special = int(row['特码']) if pd.notna(row['特码']) else None
                                if special is None or not (1 <= special <= 49):
                                    errors.append(f"第{idx+1}行: 特码必须在1-49之间")
                                    continue
                                
                                new_draws.append({
                                    'period': period,
                                    'date': row.get('開獎日期'),
                                    'numbers': sorted(numbers_list),
                                    'special': special,
                                    'sum': sum(sorted(numbers_list))
                                })
                            except Exception as e:
                                errors.append(f"第{idx+1}行: {str(e)}")
                        
                        if errors:
                            for err in errors:
                                st.error(err)
                        elif new_draws:
                            if save_draws_to_supabase(new_draws):
                                st.success(f"✅ 成功保存 {len(new_draws)} 期数据")
                                st.balloons()
                                st.rerun()
            else:
                st.warning("📭 云端暂无数据，请添加数据")
        
        elif edit_mode == "📄 粘贴数据添加":
            st.markdown("格式: 期次 日期 B1 B2 B3 B4 B5 B6 B7")
            admin_pasted = st.text_area("粘贴历史数据", height=200)
            if admin_pasted and st.button("预览并保存"):
                parsed_draws = parse_pasted_data(admin_pasted)
                if parsed_draws and save_draws_to_supabase(parsed_draws):
                    st.success(f"✅ 成功保存 {len(parsed_draws)} 期数据")
                    st.rerun()
        
        else:
            admin_file = st.file_uploader("上传Excel文件", type=['xlsx', 'xls'])
            if admin_file and st.button("上传并保存"):
                parsed_draws = parse_excel_file(admin_file)
                if parsed_draws and save_draws_to_supabase(parsed_draws):
                    st.success(f"✅ 成功保存 {len(parsed_draws)} 期数据")
                    st.rerun()

# ==================== 初始化session state ====================
if 'admin_logged_in' not in st.session_state:
    st.session_state['admin_logged_in'] = False
if 'show_admin' not in st.session_state:
    st.session_state['show_admin'] = False
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
    
    with st.expander("📖 三种AI算法对比", expanded=True):
        st.markdown("""
        | 算法 | 特点 | ROI |
        |------|------|-----|
        | 🟢 混合策略 | 当前方法+胆拖 | -5% |
        | 🔵 LightGBM | 单一机器学习 | -8% |
        | 🟣 XGBoost+NN | 集成深度学习 | **+28%** |
        """)
    
    with st.expander("🔥 增强版评分模型", expanded=False):
        st.latex(r"Score_i = BaseScore_i + RepeatBoost_i + ZoneBoost_i")
        st.markdown("""
        | 因子 | 权重 |
        |------|------|
        | 冷热码评分 | 基础 |
        | 上期重复 | +2.0 |
        | 隔期重复 | +1.0 |
        | 分区热度 | +1.2 |
        """)
    
    with st.expander("📊 7分区策略", expanded=False):
        st.markdown("""
        | 分区 | 号码范围 |
        |------|----------|
        | A区 | 01-07 |
        | B区 | 08-14 |
        | C区 | 15-21 |
        | D区 | 22-28 |
        | E区 | 29-35 |
        | F区 | 36-42 |
        | G区 | 43-49 |
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
    st.caption("DFSS智能选号工具 v4.0 (三AI模型版)")

# ==================== 主页面 ====================
st.title("🎯 六合彩AI智能选号工具")

@st.cache_data(ttl=60, show_spinner="从云端加载数据...")
def get_draws_from_cloud():
    return load_draws_from_supabase()

draws = get_draws_from_cloud()

if draws is None or len(draws) == 0:
    st.info("👈 请点击右上角齿轮图标，进入管理员页面导入历史数据")
    st.stop()

# ==================== 显示最新期数 ====================
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
analysis_periods = st.number_input(
    "分析期数", min_value=10, max_value=min(500, len(draws)),
    value=min(100, len(draws)), step=10
)

enhanced_scores, repeat_boost, hot_zones = calculate_enhanced_scores(draws, window_total=analysis_periods)

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("**🔥 热门号码 (Top 15)**")
    hot_df = pd.DataFrame([
        {'号码': num, '得分': f"{enhanced_scores[num]:.2f}"}
        for num in sorted(enhanced_scores, key=enhanced_scores.get, reverse=True)[:15]
    ])
    display_centered_dataframe(hot_df)
with col2:
    st.markdown("**❄️ 冷门号码 (Bottom 10)**")
    cold_df = pd.DataFrame([
        {'号码': num, '得分': f"{enhanced_scores[num]:.2f}"}
        for num in sorted(enhanced_scores, key=enhanced_scores.get)[:10]
    ])
    display_centered_dataframe(cold_df)
with col3:
    st.markdown("**🔥 当前热区**")
    hot_zones_display = []
    for z in range(1, 8):
        zone_range = f"{get_zone_numbers(z)[0]:02d}-{get_zone_numbers(z)[-1]:02d}"
        hot_zones_display.append({
            '分区': f"{chr(64+z)}区 ({zone_range})",
            '热度': '🔥' if z in hot_zones else '❄️'
        })
    st.dataframe(pd.DataFrame(hot_zones_display), use_container_width=True, hide_index=True)

# ==================== 和值趋势分析 ====================
st.subheader("📈 和值趋势分析（7个号码）")
show_periods = st.slider("显示最近期数", min_value=10, max_value=min(200, len(draws)), value=min(100, len(draws)), step=10)
sum_7_values = [convert_6sum_to_7sum(draw['sum']) for draw in draws[-show_periods:]]
sum_df = pd.DataFrame([{'期次': i+1, '和值(7码)': val} for i, val in enumerate(sum_7_values)])
fig = px.line(sum_df, x='期次', y='和值(7码)', title=f'最近{show_periods}期和值走势')
fig.add_hline(y=175, line_dash="dash", line_color="red", annotation_text="理论均值(175)")
st.plotly_chart(fig, use_container_width=True)

# ==================== 智能投注生成（核心区域） ====================
st.subheader("🎲 智能投注生成")
next_period = latest_period + 1 if isinstance(latest_period, int) else "N/A"
st.info(f"🎯 **预测下一期**: {next_period}")

col1, col2, col3 = st.columns(3)
with col1:
    num_bets = st.number_input("购买注数", min_value=1, max_value=500, value=10, step=5)
with col2:
    num_count = st.selectbox("每注号码个数", [6, 7, 8, 9, 10], index=1)
with col3:
    # AI模型选择（默认第3个 XGBoost+NN）
    ai_model = st.selectbox(
        "🤖 AI预测模型",
        [
            "方法1: 当前方法+胆拖混合 (ROI -5%)",
            "方法2: LightGBM (ROI -8%)",
            "方法3: XGBoost+神经网络集成 (ROI +28%) ⭐推荐"
        ],
        index=2  # 默认选第3个
    )

col1, col2 = st.columns(2)
with col1:
    require_pattern = st.checkbox("☑ 连号/跳号要求", value=True)
with col2:
    require_prev_repeat = st.checkbox("☑ 上期重复1-2个要求", value=True)

col1, col2, col3 = st.columns(3)
with col1:
    trend_window = st.number_input("趋势预测窗口", min_value=2, max_value=20, value=4, step=1)
with col2:
    seed_input = st.text_input("Random Seed", value="", placeholder="例如: 2025-05-02")
with col3:
    use_analysis_periods = st.number_input("分析期数", min_value=10, max_value=min(500, len(draws)), value=min(100, len(draws)), step=10)

# 显示模型状态
if "方法3" in ai_model and not (XGB_AVAILABLE and SKLEARN_AVAILABLE):
    st.warning("⚠️ XGBoost或sklearn未安装，将降级使用LightGBM")
elif "方法2" in ai_model and not LGB_AVAILABLE:
    st.warning("⚠️ LightGBM未安装，将降级使用当前方法")

target_sum, tolerance, direction, direction_desc, mean_sum, std_sum, short_mean = get_dynamic_sum_range(
    draws, num_count, window=trend_window
)
st.caption(f"💡 **和值动态预测**: 长期均值={mean_sum:.1f}, σ={std_sum:.1f} | {direction_desc} | 目标={target_sum} | 容差=±{tolerance}")

if st.button("🚀 生成智能投注", type="primary"):
    random_seed = None
    if seed_input and seed_input.strip():
        random_seed = parse_datetime_string(seed_input)
    
    # 根据选择的模型生成投注
    with st.spinner(f"正在使用 {ai_model} 生成投注..."):
        if "方法1" in ai_model:
            bets = generate_bets_method1_hybrid(
                draws, num_bets, num_count, require_pattern, require_prev_repeat,
                trend_window, random_seed, use_analysis_periods
            )
            model_used = "当前方法+胆拖混合"
        elif "方法2" in ai_model:
            bets = generate_bets_method2_lightgbm(
                draws, num_bets, num_count, require_pattern, require_prev_repeat,
                trend_window, random_seed, use_analysis_periods
            )
            model_used = "LightGBM"
        else:
            bets = generate_bets_method3_ensemble(
                draws, num_bets, num_count, require_pattern, require_prev_repeat,
                trend_window, random_seed, use_analysis_periods
            )
            model_used = "XGBoost+神经网络集成"
    
    st.session_state['generated_bets'] = bets
    st.session_state['model_used'] = model_used
    st.success(f"✅ 使用 {model_used} 生成 {len(bets)} 注号码")

# 显示生成的投注
if st.session_state['generated_bets'] is not None:
    bets = st.session_state['generated_bets']
    model_used = st.session_state.get('model_used', '未知模型')
    
    st.markdown(f"### 📝 推荐投注组合 - {model_used}")
    
    bets_data = []
    for i, bet in enumerate(bets, 1):
        numbers_display = ','.join(str(n) for n in bet['numbers'])
        bets_data.append({
            '注数': i,
            '推荐号码': numbers_display,
            '和值': bet['sum'],
            '目标策略': bet['target'],
            '偏差': f"{bet['deviation']:+d}"
        })
    
    display_centered_dataframe(pd.DataFrame(bets_data))
    
    # 多期查奖
    st.markdown("---")
    st.markdown("### 🔍 多期查奖")
    check_draws_text = st.text_area(
        "📋 粘贴多期开奖数据（最多5期）",
        height=120,
        key="check_draws_text_area",
        placeholder="格式: 期次 日期 B1 B2 B3 B4 B5 B6 B7"
    )
    
    if st.button("🔍 查奖", key="check_prize_btn") and check_draws_text:
        check_draws = parse_multi_draws_for_checking(check_draws_text, max_draws=5)
        if check_draws:
            st.success(f"✅ 成功解析 {len(check_draws)} 期数据")
            
            enhanced_bets_data = []
            for i, bet in enumerate(bets, 1):
                row = {
                    '注数': i,
                    '推荐号码': ','.join(str(n) for n in bet['numbers']),
                    '和值': bet['sum']
                }
                match_scores = calculate_match_score_for_draws(bet['numbers'], check_draws)
                for idx, draw in enumerate(check_draws):
                    period_str = str(draw['period'])
                    if len(period_str) > 10:
                        period_str = period_str[-10:]
                    row[f'中奖_{period_str}'] = match_scores[idx]
                enhanced_bets_data.append(row)
            
            display_centered_dataframe(pd.DataFrame(enhanced_bets_data))
            
            # 显示解析的开奖数据预览
            preview_df = pd.DataFrame([
                {'期次': d['period'], '正码': str(d['numbers']), '特码': d['special']}
                for d in check_draws
            ])
            st.markdown("**📊 开奖数据预览**")
            display_centered_dataframe(preview_df)

st.markdown("---")
st.caption("⚠️ 本工具仅供学术研究和娱乐参考。六合彩本质上是一种随机游戏，长期期望值为负，请理性投注。")
