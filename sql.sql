-- 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS job_system;
USE job_system;

-- 删除旧表（注意顺序：先删除子表，再删除父表，避免外键约束冲突）
DROP TABLE IF EXISTS `job`;
DROP TABLE IF EXISTS `category`;
DROP TABLE IF EXISTS `company`;

-- 1. 公司表
CREATE TABLE `company` (
    `id` VARCHAR(16) NOT NULL COMMENT '公司ID，主键，格式如 C001',
    `name` VARCHAR(100) NOT NULL COMMENT '公司名称',
    `company_type` VARCHAR(30) DEFAULT NULL COMMENT '公司类型（国央企、大厂、外企等）',
    `company_industry` VARCHAR(50) DEFAULT NULL COMMENT '所属行业（互联网、通信、能源等）',
    `scale` VARCHAR(20) DEFAULT NULL COMMENT '公司规模（少于50人、50-150人等）',
    `website` VARCHAR(255) DEFAULT NULL COMMENT '公司官网链接',
    `profile` TEXT COMMENT '公司简介',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='公司信息表';

-- 2. 岗位分类表
CREATE TABLE `category` (
    `id` VARCHAR(16) NOT NULL COMMENT '分类唯一标识ID，格式如 C001A01、C001A01B01',
    `name` VARCHAR(64) NOT NULL COMMENT '分类名称',
    `parent_id` VARCHAR(16) NOT NULL COMMENT '父节点ID：level=1时引用company(id)，level>=2时引用category(id)（应用层保证一致性，无数据库外键）',
    `level` TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '层级等级：1=一级分类（直属公司），2=二级分类，3=三级分类',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
    PRIMARY KEY (`id`),
    KEY `idx_parent_id` (`parent_id`),
    KEY `idx_level` (`level`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='岗位分类表';

-- 3. 职位信息表
CREATE TABLE `job` (
    `id` VARCHAR(16) NOT NULL COMMENT '职位唯一标识ID，格式如 C001J00001',
    `company_id` VARCHAR(16) NOT NULL COMMENT '所属公司ID，外键引用company(id)',
    `category_id` VARCHAR(16) NOT NULL COMMENT '所属分类ID，外键引用category(id)',
    `job_url` VARCHAR(512) NOT NULL COMMENT '职位详情页原始URL',
    `title` VARCHAR(200) NOT NULL COMMENT '职位名称',
    `salary` VARCHAR(20) DEFAULT '面议' COMMENT '薪资范围，如10k-20k、面议',
    `job_type` TINYINT UNSIGNED DEFAULT NULL COMMENT '招聘类型：0=社会招聘，1=校园招聘（允许为空）',
    `education` VARCHAR(20) DEFAULT NULL COMMENT '学历要求（大专、本科、硕士等）',
    `publish_time` DATETIME DEFAULT NULL COMMENT '职位官方发布时间',
    `location` VARCHAR(50) DEFAULT NULL COMMENT '工作地点（城市/地区）',
    `description` TEXT COMMENT '职位职责描述',
    `requirement` TEXT COMMENT '职位任职要求',
    `bonus` TEXT COMMENT '加分项（优先资格、额外要求等）',
    `work_experience` VARCHAR(100) DEFAULT NULL COMMENT '工作经验要求（如一年以上工作经验）',
    `crawl_status` TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '爬取状态：0=失败，1=成功',
    `crawled_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '爬取时间/入库时间',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_job_url` (`job_url`),
    KEY `idx_company_id` (`company_id`),
    KEY `idx_category_id` (`category_id`),
    KEY `idx_publish_time` (`publish_time`),
    KEY `idx_location` (`location`),
    KEY `idx_job_type` (`job_type`),
    KEY `idx_crawl_status` (`crawl_status`),
    CONSTRAINT `fk_job_company` FOREIGN KEY (`company_id`) REFERENCES `company` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT `fk_job_category` FOREIGN KEY (`category_id`) REFERENCES `category` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='职位信息表';

use job_system;
-- 1. 修改 level 字段的默认值为 0
ALTER TABLE `category`
MODIFY COLUMN `level` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '层级等级：0=一级分类（直属公司），1=二级分类，2=三级分类';

-- 2. 新增categoryid字段（可空）
ALTER TABLE `category`
ADD COLUMN `categoryid` INT UNSIGNED DEFAULT NULL COMMENT '官网职位分类标识ID（用于业务关联）' AFTER `level`;

-- 3. 新增crawled_job_count和official_job_count字段
USE job_system;

ALTER TABLE `category`
ADD COLUMN `crawled_job_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '爬取职位数量' AFTER `categoryid`,
ADD COLUMN `official_job_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '官网职位数量' AFTER `crawled_job_count`;