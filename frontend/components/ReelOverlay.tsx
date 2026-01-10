import React, { useRef, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ViewStyle,
  TextStyle,
  Platform,
  Animated,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

interface ReelOverlayProps {
  companyName: string;
  profileImage?: string;
  title: string;
  description: string;
  likeCount: number;
  dislikeCount: number;
  shareCount: number;
  isLiked?: boolean;
  isDisliked?: boolean;
  onLike?: () => void;
  onDislike?: () => void;
  onShare?: () => void;
  onProfilePress?: () => void;
}

// Format counts like "12.4K", "1.2M"
const formatCount = (count: number): string => {
  if (count >= 1000000) {
    return `${(count / 1000000).toFixed(1)}M`;
  }
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}K`;
  }
  return count.toString();
};

export const ReelOverlay: React.FC<ReelOverlayProps> = ({
  companyName,
  title,
  description,
  likeCount,
  dislikeCount,
  shareCount,
  isLiked = false,
  isDisliked = false,
  onLike,
  onDislike,
  onShare,
  onProfilePress,
}) => {
  const insets = useSafeAreaInsets();
  
  // Animation values
  const likeScale = useRef(new Animated.Value(1)).current;
  const dislikeScale = useRef(new Animated.Value(1)).current;

  // Animate when like state changes
  useEffect(() => {
    if (isLiked) {
      Animated.sequence([
        Animated.spring(likeScale, {
          toValue: 1.3,
          useNativeDriver: true,
          tension: 100,
          friction: 3,
        }),
        Animated.spring(likeScale, {
          toValue: 1,
          useNativeDriver: true,
          tension: 100,
          friction: 5,
        }),
      ]).start();
    }
  }, [isLiked]);

  // Animate when dislike state changes
  useEffect(() => {
    if (isDisliked) {
      Animated.sequence([
        Animated.spring(dislikeScale, {
          toValue: 1.3,
          useNativeDriver: true,
          tension: 100,
          friction: 3,
        }),
        Animated.spring(dislikeScale, {
          toValue: 1,
          useNativeDriver: true,
          tension: 100,
          friction: 5,
        }),
      ]).start();
    }
  }, [isDisliked]);

  return (
    <View style={styles.container} pointerEvents="box-none">
      {/* Right-side action stack */}
      <View style={[styles.rightActionStack, { bottom: insets.bottom + 80 }]}>
        {/* Like button */}
        <Pressable style={styles.actionButton} onPress={onLike}>
          <Animated.View style={{ transform: [{ scale: likeScale }] }}>
            <Ionicons
              name={isLiked ? 'arrow-up' : 'arrow-up-outline'}
              size={30}
              color={isLiked ? '#FF4500' : '#fff'}
            />
          </Animated.View>
          <Text style={styles.actionCount}>
            {formatCount(likeCount)}
          </Text>
        </Pressable>

        {/* Dislike button */}
        <Pressable style={styles.actionButton} onPress={onDislike}>
          <Animated.View style={{ transform: [{ scale: dislikeScale }] }}>
            <Ionicons
              name={isDisliked ? 'arrow-down' : 'arrow-down-outline'}
              size={30}
              color={isDisliked ? '#7193ff' : '#fff'}
            />
          </Animated.View>
          <Text style={styles.actionCount}>
            {formatCount(dislikeCount)}
          </Text>
        </Pressable>

        {/* Share button */}
        <Pressable style={styles.actionButton} onPress={onShare}>
          <Ionicons name="paper-plane-outline" size={28} color="#fff" />
          <Text style={styles.actionCount}>{formatCount(shareCount)}</Text>
        </Pressable>
      </View>

      {/* Bottom-left text block */}
      <View style={[styles.bottomTextBlock, { bottom: insets.bottom + 80 }]}>
        {/* Profile + Company name */}
        <Pressable style={styles.companyCluster} onPress={onProfilePress}>
          <View style={styles.profileIcon}>
            <Ionicons name="person" size={18} color="#fff" />
          </View>
          <Text style={styles.companyName} numberOfLines={1}>
            {companyName}
          </Text>
        </Pressable>

        <Text style={styles.videoTitle} numberOfLines={1}>
          {title}
        </Text>
        <Text style={styles.videoDescription} numberOfLines={2}>
          {description}
        </Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: 'space-between',
  } as ViewStyle,

  // Right-side action stack
  rightActionStack: {
    position: 'absolute',
    right: 12,
    alignItems: 'center',
    gap: 16,
  } as ViewStyle,

  actionButton: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    minHeight: 44,
    minWidth: 44,
  } as ViewStyle,

  actionCount: {
    color: '#fff',
    fontSize: 11,
    fontWeight: '600',
    marginTop: -2,
  } as TextStyle,

  // Bottom-left text block
  bottomTextBlock: {
    position: 'absolute',
    left: 12,
    right: 72,
    gap: 8,
  } as ViewStyle,

  companyCluster: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  } as ViewStyle,

  profileIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    justifyContent: 'center',
    alignItems: 'center',
  } as ViewStyle,

  companyName: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
    letterSpacing: 0.2,
    flex: 1,
  } as TextStyle,

  videoTitle: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '600',
    letterSpacing: 0.1,
  } as TextStyle,

  videoDescription: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '400',
    opacity: 0.75,
    lineHeight: 18,
  } as TextStyle,
});
