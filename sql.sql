CREATE DATABASE IF NOT EXISTS job_recruitment
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_general_ci;

USE job_recruitment;

-- 公司表
CREATE TABLE company (
    id VARCHAR(16) PRIMARY KEY COMMENT '公司ID，格式C+数字',
    name VARCHAR(100) NOT NULL UNIQUE COMMENT '公司名称',
    company_type VARCHAR(30) DEFAULT NULL COMMENT '公司类型，如国央企、大厂、外企',
    company_industry VARCHAR(50) DEFAULT NULL COMMENT '所属行业，如互联网、通信、能源',
    scale VARCHAR(20) DEFAULT NULL COMMENT '公司规模，如少于50人、10000人以上',
    website VARCHAR(255) DEFAULT NULL COMMENT '公司官网链接',
    profile TEXT COMMENT '公司简介',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='公司信息表';

-- 职位表
CREATE TABLE job (
    id VARCHAR(16) PRIMARY KEY COMMENT '职位ID，格式：公司ID+J+编号',
    company_id VARCHAR(16) NOT NULL COMMENT '所属公司ID，外键引用company(id)',
    category VARCHAR(100) NOT NULL COMMENT '所属分类，如技术-技术研发',
    job_url VARCHAR(191) NOT NULL UNIQUE COMMENT '职位详情页URL（缩短至191确保索引创建）',
    title VARCHAR(200) NOT NULL COMMENT '职位名称',
    salary VARCHAR(20) DEFAULT '面议' COMMENT '薪资范围',
    job_type TINYINT UNSIGNED DEFAULT NULL COMMENT '招聘类型：0=社招，1=校招',
    education VARCHAR(20) DEFAULT NULL COMMENT '学历要求',
    publish_time DATETIME DEFAULT NULL COMMENT '官方发布时间',
    location VARCHAR(50) DEFAULT NULL COMMENT '工作地点',
    description TEXT COMMENT '职位职责描述',
    requirement TEXT COMMENT '职位任职要求',
    bonus TEXT COMMENT '加分项',
    work_experience VARCHAR(100) DEFAULT NULL COMMENT '工作经验要求',
    crawl_status TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '爬取状态：0=失败，1=成功',
    crawled_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '爬取/入库时间',
    is_deleted TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '软删除标记：0=正常，1=待删除',
    FOREIGN KEY (company_id) REFERENCES company(id) ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='职位信息表';

-- 1.修改表结构，让 id 字段自增，完全交给数据库管理：
-- 先删除原有主键约束
ALTER TABLE job DROP PRIMARY KEY;

-- 修改 id 字段类型为 INT AUTO_INCREMENT
ALTER TABLE job MODIFY id INT AUTO_INCREMENT PRIMARY KEY;

-- 2.删除 crawl_status 字段，失败不入库，所以我们不再需要它：
ALTER TABLE job DROP COLUMN crawl_status;

-- 3.每次更新职位信息时自动刷新 crawled_at：
ALTER TABLE job MODIFY crawled_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP;

-- 4.添加索引以优化查询性能：
ALTER TABLE job ADD INDEX idx_crawled_deleted (crawled_at, is_deleted);

-- 5.修改 publish_time 字段为 VARCHAR 类型，保留原始文本格式：
ALTER TABLE job
MODIFY COLUMN publish_time VARCHAR(30) DEFAULT NULL COMMENT '官方发布时间原始文本';
