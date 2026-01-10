import React, { useState, useCallback, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Pressable,
  Dimensions,
  Modal,
  Platform,
  StatusBar,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Image } from 'expo-image';
import { Ionicons } from '@expo/vector-icons';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { Colors } from '@/constants/colors';
import { videos, videos2, videos3 } from '@/assets/data';
import { Video, ResizeMode } from 'expo-av';

const { width, height: screenHeight } = Dimensions.get('window');
const GRID_SPACING = 2;
const TILE_SIZE = (width - GRID_SPACING * 2) / 3;

// Generate placeholder thumbnails for liked videos
const generateLikedVideos = () => {
  const allVideos = [...videos, ...videos2, ...videos3];
  return allVideos.map((videoUrl, index) => ({
    id: `liked-${index}`,
    videoUrl,
    thumbnailUrl: videoUrl, // We'll use video as thumbnail
  }));
};

interface LikedVideo {
  id: string;
  videoUrl: string;
  thumbnailUrl: string;
}

export default function LikedScreen() {
  const colorScheme = useColorScheme();
  const colors = Colors[colorScheme ?? 'light'];
  
  const [likedVideos, setLikedVideos] = useState<LikedVideo[]>(generateLikedVideos());
  const [viewerVisible, setViewerVisible] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const loadMore = useCallback(() => {
    // Simulate loading more videos
    const currentLength = likedVideos.length;
    const moreVideos = videos.map((videoUrl, index) => ({
      id: `liked-${currentLength + index}`,
      videoUrl,
      thumbnailUrl: videoUrl,
    }));
    setLikedVideos((prev) => [...prev, ...moreVideos]);
  }, [likedVideos.length]);

  const openViewer = (index: number) => {
    setSelectedIndex(index);
    setViewerVisible(true);
  };

  const closeViewer = () => {
    setViewerVisible(false);
  };

  const renderGridItem = ({ item, index }: { item: LikedVideo; index: number }) => (
    <Pressable
      onPress={() => openViewer(index)}
      style={styles.gridItem}
    >
      <Image
        source={{ uri: item.thumbnailUrl }}
        style={styles.thumbnail}
        contentFit="cover"
      />
    </Pressable>
  );

  const isDark = colorScheme === 'dark';

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: colors.background }]} edges={['top']}>
      <StatusBar barStyle={isDark ? 'light-content' : 'dark-content'} />
      
      {/* Header */}
      <View style={[styles.header, { borderBottomColor: isDark ? '#262626' : '#efefef' }]}>
        <Text style={[styles.username, { color: colors.text }]}>julian</Text>
        <Pressable style={styles.menuButton}>
          <Ionicons name="menu" size={24} color={colors.text} />
        </Pressable>
      </View>

      {/* Profile Section */}
      <View style={styles.profileSection}>
        <View style={styles.profileRow}>
          {/* Profile Picture */}
          <View style={styles.profilePicContainer}>
            <View style={styles.profilePic}>
              <Ionicons name="person" size={40} color={colors.text} />
            </View>
          </View>

          {/* Stats */}
          <View style={styles.statsContainer}>
            <View style={styles.statItem}>
              <Text style={[styles.statNumber, { color: colors.text }]}>
                {likedVideos.length}
              </Text>
              <Text style={[styles.statLabel, { color: isDark ? '#a0a0a0' : '#737373' }]}>
                Liked
              </Text>
            </View>
            <View style={styles.statItem}>
              <Text style={[styles.statNumber, { color: colors.text }]}>0</Text>
              <Text style={[styles.statLabel, { color: isDark ? '#a0a0a0' : '#737373' }]}>
                Applied
              </Text>
            </View>
          </View>
        </View>
      </View>

      {/* Grid Separator */}
      <View style={[styles.gridSeparator, { borderBottomColor: isDark ? '#262626' : '#efefef' }]} />

      {/* 3-Column Grid */}
      <FlatList
        data={likedVideos}
        renderItem={renderGridItem}
        keyExtractor={(item) => item.id}
        numColumns={3}
        columnWrapperStyle={styles.columnWrapper}
        showsVerticalScrollIndicator={false}
        onEndReached={loadMore}
        onEndReachedThreshold={0.5}
        contentContainerStyle={styles.gridContainer}
      />

      {/* Full-Screen Viewer Modal */}
      <Modal
        visible={viewerVisible}
        animationType="fade"
        onRequestClose={closeViewer}
      >
        <VideoViewer
          videos={likedVideos}
          initialIndex={selectedIndex}
          onClose={closeViewer}
        />
      </Modal>
    </SafeAreaView>
  );
}

// Video Viewer Component for Modal
interface VideoViewerProps {
  videos: LikedVideo[];
  initialIndex: number;
  onClose: () => void;
}

function VideoViewer({ videos, initialIndex, onClose }: VideoViewerProps) {
  const [currentIndex, setCurrentIndex] = useState(initialIndex);
  const [isPaused, setIsPaused] = useState(false);

  const onViewableItemsChanged = useCallback((event: any) => {
    if (event.viewableItems.length > 0) {
      const newIndex = Number(event.viewableItems[0].key);
      setCurrentIndex(newIndex);
      // Unpause when scrolling to a new video
      setIsPaused(false);
    }
  }, []);

  const togglePause = () => {
    setIsPaused(!isPaused);
  };

  const renderVideo = ({ item, index }: { item: LikedVideo; index: number }) => (
    <View style={styles.videoContainer}>
      <Video
        source={{ uri: item.videoUrl }}
        style={styles.video}
        resizeMode={ResizeMode.COVER}
        shouldPlay={currentIndex === index && !isPaused}
        isLooping
      />
      
      {/* Tap overlay to pause/play */}
      <Pressable onPress={togglePause} style={styles.tapOverlay} />

      {/* Pause indicator that sticks to this video */}
      {isPaused && currentIndex === index && (
        <View style={styles.pauseIndicator}>
          <Ionicons name="pause" size={60} color="#fff" style={styles.pauseIcon} />
        </View>
      )}
    </View>
  );

  return (
    <View style={styles.viewerContainer}>
      <StatusBar barStyle="light-content" />
      
      {/* Close Button */}
      <Pressable style={styles.closeButton} onPress={onClose}>
        <Ionicons name="close" size={30} color="#fff" />
      </Pressable>

      {/* Vertical Video Feed */}
      <FlatList
        data={videos}
        renderItem={renderVideo}
        keyExtractor={(item, index) => index.toString()}
        pagingEnabled
        showsVerticalScrollIndicator={false}
        snapToInterval={screenHeight}
        decelerationRate="fast"
        onViewableItemsChanged={onViewableItemsChanged}
        initialScrollIndex={initialIndex}
        getItemLayout={(data, index) => ({
          length: screenHeight,
          offset: screenHeight * index,
          index,
        })}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    position: 'relative',
  },
  username: {
    fontSize: 16,
    fontWeight: '600',
  },
  menuButton: {
    position: 'absolute',
    right: 16,
    padding: 4,
  },
  profileSection: {
    paddingHorizontal: 16,
    paddingVertical: 16,
  },
  profileRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  profilePicContainer: {
    marginRight: 32,
  },
  profilePic: {
    width: 86,
    height: 86,
    borderRadius: 43,
    backgroundColor: 'rgba(128, 128, 128, 0.2)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  statsContainer: {
    flex: 1,
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  statItem: {
    alignItems: 'center',
  },
  statNumber: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 2,
  },
  statLabel: {
    fontSize: 13,
    fontWeight: '400',
  },
  gridSeparator: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    marginTop: 8,
  },
  gridContainer: {
    paddingTop: GRID_SPACING,
  },
  columnWrapper: {
    gap: GRID_SPACING,
    paddingHorizontal: GRID_SPACING,
    marginBottom: GRID_SPACING,
  },
  gridItem: {
    width: TILE_SIZE,
    height: TILE_SIZE,
    backgroundColor: '#e0e0e0',
  },
  thumbnail: {
    width: '100%',
    height: '100%',
  },
  // Viewer Modal Styles
  viewerContainer: {
    flex: 1,
    backgroundColor: '#000',
  },
  closeButton: {
    position: 'absolute',
    top: Platform.OS === 'ios' ? 50 : 20,
    left: 16,
    zIndex: 100,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  videoContainer: {
    width,
    height: screenHeight,
    backgroundColor: '#000',
  },
  video: {
    width: '100%',
    height: '100%',
  },
  tapOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'transparent',
  },
  pauseIndicator: {
    position: 'absolute',
    top: '50%',
    left: '50%',
    transform: [{ translateX: -30 }, { translateY: -30 }],
    width: 60,
    height: 60,
    justifyContent: 'center',
    alignItems: 'center',
    pointerEvents: 'none',
  },
  pauseIcon: {
    opacity: 0.3,
  },
});
